from __future__ import annotations

from uuid import UUID

from sqlalchemy import asc, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import GameStatus, Platform
from app.features.games.models import Game
from app.features.services.models import Service, ServiceOption

_SORTABLE_FIELDS = {
    "sort_order": Service.sort_order,
    "title": Service.title,
    "created_at": Service.created_at,
}


def _parse_sort(sort: str | None):
    if not sort:
        return [asc(Service.sort_order), asc(Service.created_at)]
    descending = sort.startswith("-")
    field_name = sort[1:] if descending else sort
    column = _SORTABLE_FIELDS.get(field_name)
    if column is None:
        return [asc(Service.sort_order), asc(Service.created_at)]
    return [desc(column) if descending else asc(column)]


class ServiceRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _live(self):
        return select(Service).where(Service.is_deleted.is_(False))

    async def list_paginated(
        self,
        *,
        limit: int,
        offset: int,
        game_id: UUID | None = None,
        platform: Platform | None = None,
        is_active: bool | None = None,
        is_featured: bool | None = None,
        search: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[tuple[Service, int, object, object]], int]:
        opts_count = (
            select(func.count(ServiceOption.id))
            .where(ServiceOption.service_id == Service.id)
            .correlate(Service)
            .scalar_subquery()
            .label("options_count")
        )
        default_usd = (
            select(ServiceOption.price_usd)
            .where(
                ServiceOption.service_id == Service.id,
                ServiceOption.is_default.is_(True),
            )
            .correlate(Service)
            .limit(1)
            .scalar_subquery()
            .label("default_price_usd")
        )
        default_eur = (
            select(ServiceOption.price_eur)
            .where(
                ServiceOption.service_id == Service.id,
                ServiceOption.is_default.is_(True),
            )
            .correlate(Service)
            .limit(1)
            .scalar_subquery()
            .label("default_price_eur")
        )

        items_q = (
            select(Service, opts_count, default_usd, default_eur)
            .options(selectinload(Service.game))
            .where(Service.is_deleted.is_(False))
        )
        count_q = select(func.count()).select_from(Service).where(Service.is_deleted.is_(False))

        if game_id is not None:
            items_q = items_q.where(Service.game_id == game_id)
            count_q = count_q.where(Service.game_id == game_id)
        if platform is not None:
            items_q = items_q.where(Service.platform == platform)
            count_q = count_q.where(Service.platform == platform)
        if is_active is not None:
            items_q = items_q.where(Service.is_active.is_(is_active))
            count_q = count_q.where(Service.is_active.is_(is_active))
        if is_featured is not None:
            items_q = items_q.where(Service.is_featured.is_(is_featured))
            count_q = count_q.where(Service.is_featured.is_(is_featured))
        if search:
            pattern = f"%{search.strip()}%"
            cond = or_(Service.title.ilike(pattern), Service.slug.ilike(pattern))
            items_q = items_q.where(cond)
            count_q = count_q.where(cond)

        for clause in _parse_sort(sort):
            items_q = items_q.order_by(clause)

        items_q = items_q.limit(limit).offset(offset)

        rows = (await self.db.execute(items_q)).all()
        total = (await self.db.execute(count_q)).scalar_one()
        return [(row[0], int(row[1] or 0), row[2], row[3]) for row in rows], total

    async def list_public(
        self,
        *,
        game_slug: str | None = None,
        platform: Platform | None = None,
        featured: bool | None = None,
    ) -> list[Service]:
        q = (
            select(Service)
            .options(selectinload(Service.options), selectinload(Service.game))
            .where(Service.is_deleted.is_(False), Service.is_active.is_(True))
            .order_by(asc(Service.sort_order), asc(Service.created_at))
        )
        if game_slug is not None:
            q = q.join(Game, Game.id == Service.game_id).where(
                Game.slug == game_slug,
                Game.is_deleted.is_(False),
                Game.status != GameStatus.HIDDEN,
            )
        if platform is not None:
            q = q.where(Service.platform == platform)
        if featured is not None:
            q = q.where(Service.is_featured.is_(featured))

        return list((await self.db.execute(q)).scalars().all())

    async def get_public_by_slug(self, slug: str) -> Service | None:
        q = (
            select(Service)
            .options(selectinload(Service.options), selectinload(Service.game))
            .where(
                Service.slug == slug,
                Service.is_deleted.is_(False),
                Service.is_active.is_(True),
            )
        )
        return (await self.db.execute(q)).scalar_one_or_none()

    async def get_with_relations(self, service_id: UUID) -> Service | None:
        q = (
            self._live()
            .options(selectinload(Service.options), selectinload(Service.game))
            .where(Service.id == service_id)
        )
        return (await self.db.execute(q)).scalar_one_or_none()

    async def get_by_id(self, service_id: UUID) -> Service | None:
        q = self._live().where(Service.id == service_id)
        return (await self.db.execute(q)).scalar_one_or_none()

    async def get_by_slug(self, slug: str, *, exclude_id: UUID | None = None) -> Service | None:
        q = self._live().where(Service.slug == slug)
        if exclude_id is not None:
            q = q.where(Service.id != exclude_id)
        return (await self.db.execute(q)).scalar_one_or_none()

    async def add(self, service: Service) -> Service:
        self.db.add(service)
        await self.db.flush()
        return service

    async def bulk_update_sort_order(self, items: list[tuple[UUID, int]]) -> int:
        updated = 0
        for service_id, sort_order in items:
            stmt = (
                update(Service)
                .where(Service.id == service_id, Service.is_deleted.is_(False))
                .values(sort_order=sort_order)
            )
            result = await self.db.execute(stmt)
            updated += result.rowcount or 0
        return updated


class ServiceOptionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_by_service(self, service_id: UUID) -> list[ServiceOption]:
        q = (
            select(ServiceOption)
            .where(ServiceOption.service_id == service_id)
            .order_by(asc(ServiceOption.sort_order), asc(ServiceOption.created_at))
        )
        return list((await self.db.execute(q)).scalars().all())

    async def get_by_id(
        self, option_id: UUID, *, service_id: UUID | None = None
    ) -> ServiceOption | None:
        q = select(ServiceOption).where(ServiceOption.id == option_id)
        if service_id is not None:
            q = q.where(ServiceOption.service_id == service_id)
        return (await self.db.execute(q)).scalar_one_or_none()

    async def add(self, option: ServiceOption) -> ServiceOption:
        self.db.add(option)
        await self.db.flush()
        return option

    async def delete(self, option: ServiceOption) -> None:
        await self.db.delete(option)
        await self.db.flush()

    async def unset_default(self, service_id: UUID, *, exclude_id: UUID | None = None) -> int:
        stmt = (
            update(ServiceOption)
            .where(
                ServiceOption.service_id == service_id,
                ServiceOption.is_default.is_(True),
            )
            .values(is_default=False)
        )
        if exclude_id is not None:
            stmt = stmt.where(ServiceOption.id != exclude_id)
        result = await self.db.execute(stmt)
        return result.rowcount or 0

    async def bulk_update_sort_order(self, service_id: UUID, items: list[tuple[UUID, int]]) -> int:
        updated = 0
        for option_id, sort_order in items:
            stmt = (
                update(ServiceOption)
                .where(
                    ServiceOption.id == option_id,
                    ServiceOption.service_id == service_id,
                )
                .values(sort_order=sort_order)
            )
            result = await self.db.execute(stmt)
            updated += result.rowcount or 0
        return updated
