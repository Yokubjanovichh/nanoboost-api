from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Platform
from app.core.exceptions import ConflictError, NotFoundError
from app.features.games.repository import GameRepository
from app.features.services.models import Service, ServiceOption
from app.features.services.repository import ServiceOptionRepository, ServiceRepository
from app.features.services.schemas import (
    ReorderRequest,
    ServiceCreate,
    ServiceOptionCreate,
    ServiceOptionUpdate,
    ServiceUpdate,
)


def _what_you_get_to_dict(items: list) -> list[dict]:
    return [item.model_dump() for item in items]


def _sections_to_dict(items: list) -> list[dict]:
    return [item.model_dump() for item in items]


class ServiceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ServiceRepository(db)
        self.options_repo = ServiceOptionRepository(db)
        self.games_repo = GameRepository(db)

    async def create(self, payload: ServiceCreate) -> Service:
        if await self.repo.get_by_slug(payload.slug) is not None:
            raise ConflictError("Service with this slug already exists")

        game = await self.games_repo.get_by_id(payload.game_id)
        if game is None:
            raise NotFoundError("Game")

        service = Service(
            game_id=payload.game_id,
            slug=payload.slug,
            title=payload.title,
            platform=payload.platform,
            image_url=payload.image_url,
            image_alt=payload.image_alt,
            description=list(payload.description),
            what_you_get=_what_you_get_to_dict(payload.what_you_get),
            sections=_sections_to_dict(payload.sections),
            seo_title=payload.seo_title,
            seo_description=payload.seo_description,
            is_featured=payload.is_featured,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
        )
        for opt_payload in payload.options:
            service.options.append(
                ServiceOption(
                    label=opt_payload.label,
                    price_usd=opt_payload.price_usd,
                    price_eur=opt_payload.price_eur,
                    is_default=opt_payload.is_default,
                    sort_order=opt_payload.sort_order,
                )
            )
        await self.repo.add(service)
        await self.db.commit()
        return await self._reload_with_relations(service.id)

    async def get(self, service_id: UUID) -> Service:
        service = await self.repo.get_with_relations(service_id)
        if service is None:
            raise NotFoundError("Service")
        return service

    async def list(
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
        return await self.repo.list_paginated(
            limit=limit,
            offset=offset,
            game_id=game_id,
            platform=platform,
            is_active=is_active,
            is_featured=is_featured,
            search=search,
            sort=sort,
        )

    async def list_public(
        self,
        *,
        game_slug: str | None = None,
        platform: Platform | None = None,
        featured: bool | None = None,
    ) -> list[Service]:
        return await self.repo.list_public(
            game_slug=game_slug, platform=platform, featured=featured
        )

    async def get_public(self, slug: str) -> Service:
        service = await self.repo.get_public_by_slug(slug)
        if service is None:
            raise NotFoundError("Service")
        return service

    async def update(self, service_id: UUID, payload: ServiceUpdate) -> Service:
        service = await self.get(service_id)

        if payload.slug is not None and payload.slug != service.slug:
            existing = await self.repo.get_by_slug(payload.slug, exclude_id=service.id)
            if existing is not None:
                raise ConflictError("Service with this slug already exists")
            service.slug = payload.slug

        if payload.title is not None:
            service.title = payload.title
        if payload.platform is not None:
            service.platform = payload.platform
        if payload.image_url is not None:
            service.image_url = payload.image_url
        if payload.image_alt is not None:
            service.image_alt = payload.image_alt
        if payload.description is not None:
            service.description = list(payload.description)
        if payload.what_you_get is not None:
            service.what_you_get = _what_you_get_to_dict(payload.what_you_get)
        if payload.sections is not None:
            service.sections = _sections_to_dict(payload.sections)
        if payload.seo_title is not None:
            service.seo_title = payload.seo_title
        if payload.seo_description is not None:
            service.seo_description = payload.seo_description
        if payload.is_featured is not None:
            service.is_featured = payload.is_featured
        if payload.sort_order is not None:
            service.sort_order = payload.sort_order
        if payload.is_active is not None:
            service.is_active = payload.is_active

        await self.db.commit()
        return await self._reload_with_relations(service.id)

    async def toggle_active(self, service_id: UUID) -> Service:
        service = await self.get(service_id)
        service.is_active = not service.is_active
        await self.db.commit()
        return await self._reload_with_relations(service.id)

    async def toggle_featured(self, service_id: UUID) -> Service:
        service = await self.get(service_id)
        service.is_featured = not service.is_featured
        await self.db.commit()
        return await self._reload_with_relations(service.id)

    async def soft_delete(self, service_id: UUID) -> None:
        service = await self.repo.get_by_id(service_id)
        if service is None:
            raise NotFoundError("Service")
        service.is_deleted = True
        service.is_active = False
        await self.db.commit()

    async def reorder(self, payload: ReorderRequest) -> int:
        pairs = [(item.id, item.sort_order) for item in payload.items]
        updated = await self.repo.bulk_update_sort_order(pairs)
        if updated == 0:
            raise NotFoundError("None of the services")
        await self.db.commit()
        return updated

    async def _reload_with_relations(self, service_id: UUID) -> Service:
        service = await self.repo.get_with_relations(service_id)
        if service is None:
            raise NotFoundError("Service")
        return service


class ServiceOptionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ServiceOptionRepository(db)
        self.services_repo = ServiceRepository(db)

    async def _ensure_service(self, service_id: UUID) -> None:
        service = await self.services_repo.get_by_id(service_id)
        if service is None:
            raise NotFoundError("Service")

    async def list(self, service_id: UUID) -> list[ServiceOption]:
        await self._ensure_service(service_id)
        return await self.repo.list_by_service(service_id)

    async def create(
        self, service_id: UUID, payload: ServiceOptionCreate
    ) -> ServiceOption:
        await self._ensure_service(service_id)

        if payload.is_default:
            await self.repo.unset_default(service_id)

        option = ServiceOption(
            service_id=service_id,
            label=payload.label,
            price_usd=payload.price_usd,
            price_eur=payload.price_eur,
            is_default=payload.is_default,
            sort_order=payload.sort_order,
        )
        await self.repo.add(option)
        await self.db.commit()
        await self.db.refresh(option)
        return option

    async def update(
        self, service_id: UUID, option_id: UUID, payload: ServiceOptionUpdate
    ) -> ServiceOption:
        option = await self.repo.get_by_id(option_id, service_id=service_id)
        if option is None:
            raise NotFoundError("Option")

        if payload.is_default is True and not option.is_default:
            await self.repo.unset_default(service_id, exclude_id=option.id)

        if payload.label is not None:
            option.label = payload.label
        if payload.price_usd is not None:
            option.price_usd = payload.price_usd
        if payload.price_eur is not None:
            option.price_eur = payload.price_eur
        if payload.is_default is not None:
            option.is_default = payload.is_default
        if payload.sort_order is not None:
            option.sort_order = payload.sort_order

        await self.db.commit()
        await self.db.refresh(option)
        return option

    async def delete(self, service_id: UUID, option_id: UUID) -> None:
        option = await self.repo.get_by_id(option_id, service_id=service_id)
        if option is None:
            raise NotFoundError("Option")
        await self.repo.delete(option)
        await self.db.commit()

    async def reorder(
        self, service_id: UUID, payload: ReorderRequest
    ) -> int:
        await self._ensure_service(service_id)
        pairs = [(item.id, item.sort_order) for item in payload.items]
        updated = await self.repo.bulk_update_sort_order(service_id, pairs)
        if updated == 0:
            raise NotFoundError("None of the options")
        await self.db.commit()
        return updated
