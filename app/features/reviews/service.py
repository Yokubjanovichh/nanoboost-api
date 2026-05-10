from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.features.reviews.models import Review
from app.features.reviews.repository import ReviewRepository
from app.features.reviews.schemas import (
    ReviewCreate,
    ReviewReorderRequest,
    ReviewUpdate,
)
from app.features.services.repository import ServiceRepository


class ReviewService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ReviewRepository(db)
        self.services = ServiceRepository(db)

    async def _validate_service(self, service_id: UUID | None) -> None:
        if service_id is None:
            return
        service = await self.services.get_by_id(service_id)
        if service is None:
            raise NotFoundError("Service")

    async def create(self, payload: ReviewCreate) -> Review:
        await self._validate_service(payload.service_id)
        review = Review(
            author_name=payload.author_name,
            service_id=payload.service_id,
            rating=payload.rating,
            text=payload.text,
            is_featured=payload.is_featured,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
        )
        await self.repo.add(review)
        await self.db.commit()
        return await self._reload(review.id)

    async def get(self, review_id: UUID) -> Review:
        review = await self.repo.get_by_id(review_id)
        if review is None:
            raise NotFoundError("Review")
        return review

    async def list(
        self,
        *,
        limit: int,
        offset: int,
        service_id: UUID | None = None,
        is_active: bool | None = None,
        is_featured: bool | None = None,
        search: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[Review], int]:
        return await self.repo.list_paginated(
            limit=limit,
            offset=offset,
            service_id=service_id,
            is_active=is_active,
            is_featured=is_featured,
            search=search,
            sort=sort,
        )

    async def list_public(
        self,
        *,
        service_id: UUID | None = None,
        featured: bool | None = None,
    ) -> list[Review]:
        return await self.repo.list_public(service_id=service_id, featured=featured)

    async def update(self, review_id: UUID, payload: ReviewUpdate) -> Review:
        review = await self.get(review_id)

        if payload.service_id is not None:
            await self._validate_service(payload.service_id)
            review.service_id = payload.service_id
        if payload.author_name is not None:
            review.author_name = payload.author_name
        if payload.rating is not None:
            review.rating = payload.rating
        if payload.text is not None:
            review.text = payload.text
        if payload.is_featured is not None:
            review.is_featured = payload.is_featured
        if payload.sort_order is not None:
            review.sort_order = payload.sort_order
        if payload.is_active is not None:
            review.is_active = payload.is_active

        await self.db.commit()
        return await self._reload(review.id)

    async def toggle_active(self, review_id: UUID) -> Review:
        review = await self.get(review_id)
        review.is_active = not review.is_active
        await self.db.commit()
        return await self._reload(review.id)

    async def toggle_featured(self, review_id: UUID) -> Review:
        review = await self.get(review_id)
        review.is_featured = not review.is_featured
        await self.db.commit()
        return await self._reload(review.id)

    async def soft_delete(self, review_id: UUID) -> None:
        review = await self.get(review_id)
        review.is_deleted = True
        review.is_active = False
        await self.db.commit()

    async def reorder(self, payload: ReviewReorderRequest) -> int:
        pairs = [(item.id, item.sort_order) for item in payload.items]
        updated = await self.repo.bulk_update_sort_order(pairs)
        if updated == 0:
            raise NotFoundError("None of the reviews")
        await self.db.commit()
        return updated

    async def _reload(self, review_id: UUID) -> Review:
        review = await self.repo.get_by_id(review_id)
        if review is None:
            raise NotFoundError("Review")
        return review
