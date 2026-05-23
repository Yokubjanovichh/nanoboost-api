from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.features.faqs.models import GameFAQ
from app.features.faqs.repository import FAQRepository
from app.features.faqs.schemas import (
    FAQCreate,
    FAQReorderRequest,
    FAQUpdate,
)


class FAQService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FAQRepository(db)

    async def list_public(self, game_slug: str) -> list[GameFAQ]:
        """Unknown slugs return [] by contract — the storefront should
        render an empty FAQ block, not a 404."""
        return await self.repo.list_public(game_slug)

    async def list_admin(self, game_slug: str) -> list[GameFAQ]:
        return await self.repo.list_admin(game_slug)

    async def create(self, game_slug: str, payload: FAQCreate) -> GameFAQ:
        faq = GameFAQ(
            game_slug=game_slug,
            question=payload.question,
            answer=payload.answer,
            order_index=payload.order_index,
            is_active=payload.is_active,
        )
        await self.repo.add(faq)
        await self.db.commit()
        await self.db.refresh(faq)
        return faq

    async def get(self, faq_id: int) -> GameFAQ:
        faq = await self.repo.get_by_id(faq_id)
        if faq is None:
            raise NotFoundError("FAQ")
        return faq

    async def update(self, faq_id: int, payload: FAQUpdate) -> GameFAQ:
        faq = await self.get(faq_id)

        # Only mutate fields the client explicitly sent — model_dump with
        # exclude_unset preserves the "missing vs null" distinction so we
        # can deactivate a FAQ via `{"is_active": false}` without having
        # to resend the rest of the row.
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(faq, field, value)

        await self.db.commit()
        await self.db.refresh(faq)
        return faq

    async def delete(self, faq_id: int) -> None:
        faq = await self.get(faq_id)
        await self.repo.delete(faq)
        await self.db.commit()

    async def reorder(self, game_slug: str, payload: FAQReorderRequest) -> int:
        pairs = [(item.id, item.order_index) for item in payload.order]
        updated = await self.repo.bulk_update_order(game_slug, pairs)
        if updated == 0:
            raise NotFoundError("None of the FAQs")
        await self.db.commit()
        return updated
