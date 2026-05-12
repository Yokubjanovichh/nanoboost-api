from __future__ import annotations

from uuid import UUID

from sqlalchemy import asc, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.features.reviews.models import Review

_SORTABLE = {
    "sort_order": Review.sort_order,
    "rating": Review.rating,
    "created_at": Review.created_at,
}


def _parse_sort(sort: str | None):
    if not sort:
        return [asc(Review.sort_order), desc(Review.created_at)]
    descending = sort.startswith("-")
    field = sort[1:] if descending else sort
    column = _SORTABLE.get(field)
    if column is None:
        return [asc(Review.sort_order), desc(Review.created_at)]
    return [desc(column) if descending else asc(column)]


class ReviewRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _live(self):
        return select(Review).where(Review.is_deleted.is_(False))

    async def list_paginated(
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
        items_q = self._live().options(selectinload(Review.service))
        count_q = select(func.count()).select_from(Review).where(Review.is_deleted.is_(False))

        if service_id is not None:
            items_q = items_q.where(Review.service_id == service_id)
            count_q = count_q.where(Review.service_id == service_id)
        if is_active is not None:
            items_q = items_q.where(Review.is_active.is_(is_active))
            count_q = count_q.where(Review.is_active.is_(is_active))
        if is_featured is not None:
            items_q = items_q.where(Review.is_featured.is_(is_featured))
            count_q = count_q.where(Review.is_featured.is_(is_featured))
        if search:
            pattern = f"%{search.strip()}%"
            cond = or_(
                Review.author_name.ilike(pattern),
                Review.text.ilike(pattern),
            )
            items_q = items_q.where(cond)
            count_q = count_q.where(cond)

        for clause in _parse_sort(sort):
            items_q = items_q.order_by(clause)

        items_q = items_q.limit(limit).offset(offset)

        items = (await self.db.execute(items_q)).scalars().all()
        total = (await self.db.execute(count_q)).scalar_one()
        return list(items), total

    async def list_public(
        self,
        *,
        service_id: UUID | None = None,
        featured: bool | None = None,
    ) -> list[Review]:
        q = (
            select(Review)
            .options(selectinload(Review.service))
            .where(Review.is_deleted.is_(False), Review.is_active.is_(True))
            .order_by(asc(Review.sort_order), desc(Review.created_at))
        )
        if service_id is not None:
            q = q.where(Review.service_id == service_id)
        if featured is not None:
            q = q.where(Review.is_featured.is_(featured))
        return list((await self.db.execute(q)).scalars().all())

    async def get_by_id(self, review_id: UUID) -> Review | None:
        q = self._live().options(selectinload(Review.service)).where(Review.id == review_id)
        return (await self.db.execute(q)).scalar_one_or_none()

    async def add(self, review: Review) -> Review:
        self.db.add(review)
        await self.db.flush()
        return review

    async def bulk_update_sort_order(self, items: list[tuple[UUID, int]]) -> int:
        updated = 0
        for review_id, sort_order in items:
            stmt = (
                update(Review)
                .where(Review.id == review_id, Review.is_deleted.is_(False))
                .values(sort_order=sort_order)
            )
            result = await self.db.execute(stmt)
            updated += result.rowcount or 0
        return updated
