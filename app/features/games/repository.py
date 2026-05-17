from uuid import UUID

from sqlalchemy import asc, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import GameStatus
from app.features.games.models import Game
from app.features.services.models import Service

_SORTABLE_FIELDS = {
    "sort_order": Game.sort_order,
    "name": Game.name,
    "created_at": Game.created_at,
}


def _parse_sort(sort: str | None):
    if not sort:
        return [asc(Game.sort_order), asc(Game.created_at)]
    descending = sort.startswith("-")
    field_name = sort[1:] if descending else sort
    column = _SORTABLE_FIELDS.get(field_name)
    if column is None:
        return [asc(Game.sort_order), asc(Game.created_at)]
    return [desc(column) if descending else asc(column)]


class GameRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _base_query(self):
        return select(Game).where(Game.is_deleted.is_(False))

    async def list_paginated(
        self,
        *,
        limit: int,
        offset: int,
        status: GameStatus | None = None,
        search: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[Game], int]:
        items_q = self._base_query()
        count_q = select(func.count()).select_from(Game).where(Game.is_deleted.is_(False))

        if status is not None:
            items_q = items_q.where(Game.status == status)
            count_q = count_q.where(Game.status == status)

        if search:
            pattern = f"%{search.strip()}%"
            cond = or_(Game.name.ilike(pattern), Game.slug.ilike(pattern))
            items_q = items_q.where(cond)
            count_q = count_q.where(cond)

        for clause in _parse_sort(sort):
            items_q = items_q.order_by(clause)

        items_q = items_q.limit(limit).offset(offset)

        items = (await self.db.execute(items_q)).scalars().all()
        total = (await self.db.execute(count_q)).scalar_one()
        return list(items), total

    async def list_public(self) -> list[tuple[Game, int]]:
        # Public site shows active + coming_soon (latter rendered disabled).
        # Hidden games are filtered out entirely.
        #
        # The service-count join *must* live in the ON clause, not WHERE:
        # otherwise games with zero matching services collapse out of the
        # result (LEFT JOIN with a WHERE on the right side acts like an
        # INNER JOIN). count(Service.id) returns 0 cleanly for unmatched
        # rows because the right side is NULL.
        q = (
            select(Game, func.count(Service.id).label("service_count"))
            .outerjoin(
                Service,
                (Service.game_id == Game.id)
                & Service.is_active.is_(True)
                & Service.is_deleted.is_(False),
            )
            .where(Game.is_deleted.is_(False), Game.status != GameStatus.HIDDEN)
            .group_by(Game.id)
            .order_by(asc(Game.sort_order), asc(Game.created_at))
        )
        return [(row[0], row[1]) for row in (await self.db.execute(q)).all()]

    async def get_by_id(self, game_id: UUID) -> Game | None:
        q = self._base_query().where(Game.id == game_id)
        return (await self.db.execute(q)).scalar_one_or_none()

    async def get_by_slug(self, slug: str, *, exclude_id: UUID | None = None) -> Game | None:
        q = self._base_query().where(Game.slug == slug)
        if exclude_id is not None:
            q = q.where(Game.id != exclude_id)
        return (await self.db.execute(q)).scalar_one_or_none()

    async def add(self, game: Game) -> Game:
        self.db.add(game)
        await self.db.flush()
        await self.db.refresh(game)
        return game

    async def bulk_update_sort_order(self, items: list[tuple[UUID, int]]) -> int:
        updated = 0
        for game_id, sort_order in items:
            stmt = (
                update(Game)
                .where(Game.id == game_id, Game.is_deleted.is_(False))
                .values(sort_order=sort_order)
            )
            result = await self.db.execute(stmt)
            updated += result.rowcount or 0
        return updated
