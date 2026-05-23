from sqlalchemy import asc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.faqs.models import GameFAQ


class FAQRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_public(self, game_slug: str) -> list[GameFAQ]:
        """Storefront read — active only, deterministic order."""
        q = (
            select(GameFAQ)
            .where(GameFAQ.game_slug == game_slug, GameFAQ.is_active.is_(True))
            .order_by(asc(GameFAQ.order_index), asc(GameFAQ.id))
        )
        return list((await self.db.execute(q)).scalars().all())

    async def list_admin(self, game_slug: str) -> list[GameFAQ]:
        """Admin view — includes inactive rows, same sort so the table
        order on the admin side matches the public order one-to-one."""
        q = (
            select(GameFAQ)
            .where(GameFAQ.game_slug == game_slug)
            .order_by(asc(GameFAQ.order_index), asc(GameFAQ.id))
        )
        return list((await self.db.execute(q)).scalars().all())

    async def get_by_id(self, faq_id: int) -> GameFAQ | None:
        return await self.db.get(GameFAQ, faq_id)

    async def add(self, faq: GameFAQ) -> GameFAQ:
        self.db.add(faq)
        await self.db.flush()
        await self.db.refresh(faq)
        return faq

    async def delete(self, faq: GameFAQ) -> None:
        await self.db.delete(faq)

    async def bulk_update_order(self, game_slug: str, items: list[tuple[int, int]]) -> int:
        """Bulk reorder. Each (faq_id, order_index) must belong to the
        slug passed in — prevents an admin from accidentally renumbering
        a different game's FAQs by sending the wrong id."""
        updated = 0
        for faq_id, order_index in items:
            stmt = (
                update(GameFAQ)
                .where(GameFAQ.id == faq_id, GameFAQ.game_slug == game_slug)
                .values(order_index=order_index)
            )
            result = await self.db.execute(stmt)
            updated += result.rowcount or 0
        return updated
