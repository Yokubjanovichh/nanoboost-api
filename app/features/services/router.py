from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status

from app.core.constants import Platform
from app.core.dependencies import DbSession
from app.core.permissions import (
    require_admin_or_above,
    require_any_authenticated,
    require_manager_or_above,
)
from app.features.services.schemas import (
    PublicServiceRead,
    ReorderRequest,
    ReorderResponse,
    ServiceCreate,
    ServiceDetailRead,
    ServiceOptionCreate,
    ServiceOptionRead,
    ServiceOptionUpdate,
    ServiceRead,
    ServiceUpdate,
)
from app.features.services.service import ServiceOptionService, ServiceService
from app.features.users.models import User
from app.shared.pagination import Paginated, PaginationDep, paginate

router = APIRouter(prefix="/services", tags=["services"])

ReadAccess = Annotated[User, Depends(require_any_authenticated)]
ManagerAccess = Annotated[User, Depends(require_manager_or_above)]
AdminAccess = Annotated[User, Depends(require_admin_or_above)]


def _to_read(
    service,
    *,
    options_count: int = 0,
    default_price_usd=None,
    default_price_eur=None,
) -> ServiceRead:
    base = ServiceRead.model_validate(service)
    return base.model_copy(
        update={
            "options_count": options_count,
            "default_option_price_usd": default_price_usd,
            "default_option_price_eur": default_price_eur,
        }
    )


def _detail_default_prices(service) -> tuple[object, object]:
    for opt in service.options:
        if opt.is_default:
            return opt.price_usd, opt.price_eur
    return None, None


def _to_detail(service) -> ServiceDetailRead:
    base = ServiceDetailRead.model_validate(service)
    default_usd, default_eur = _detail_default_prices(service)
    return base.model_copy(
        update={
            "options_count": len(service.options),
            "default_option_price_usd": default_usd,
            "default_option_price_eur": default_eur,
        }
    )


@router.get("", response_model=Paginated[ServiceRead])
async def list_services(
    db: DbSession,
    _: ReadAccess,
    page: PaginationDep,
    game_id: Annotated[UUID | None, Query()] = None,
    platform: Annotated[Platform | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
    is_featured: Annotated[bool | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    sort: Annotated[str | None, Query()] = None,
) -> Paginated[ServiceRead]:
    rows, total = await ServiceService(db).list(
        limit=page.limit,
        offset=page.offset,
        game_id=game_id,
        platform=platform,
        is_active=is_active,
        is_featured=is_featured,
        search=search,
        sort=sort,
    )
    items = [
        _to_read(
            svc,
            options_count=count,
            default_price_usd=usd,
            default_price_eur=eur,
        )
        for svc, count, usd, eur in rows
    ]
    return paginate(items, total=total, params=page)


@router.post("", response_model=ServiceDetailRead, status_code=status.HTTP_201_CREATED)
async def create_service(
    payload: ServiceCreate, db: DbSession, _: ManagerAccess
) -> ServiceDetailRead:
    service = await ServiceService(db).create(payload)
    return _to_detail(service)


@router.post("/reorder", response_model=ReorderResponse)
async def reorder_services(
    payload: ReorderRequest, db: DbSession, _: ManagerAccess
) -> ReorderResponse:
    updated = await ServiceService(db).reorder(payload)
    return ReorderResponse(updated=updated)


@router.get("/{service_id}", response_model=ServiceDetailRead)
async def get_service(service_id: UUID, db: DbSession, _: ReadAccess) -> ServiceDetailRead:
    service = await ServiceService(db).get(service_id)
    return _to_detail(service)


@router.patch("/{service_id}", response_model=ServiceDetailRead)
async def update_service(
    service_id: UUID, payload: ServiceUpdate, db: DbSession, _: ManagerAccess
) -> ServiceDetailRead:
    service = await ServiceService(db).update(service_id, payload)
    return _to_detail(service)


@router.patch("/{service_id}/toggle", response_model=ServiceDetailRead)
async def toggle_service_active(
    service_id: UUID, db: DbSession, _: ManagerAccess
) -> ServiceDetailRead:
    service = await ServiceService(db).toggle_active(service_id)
    return _to_detail(service)


@router.patch("/{service_id}/featured", response_model=ServiceDetailRead)
async def toggle_service_featured(
    service_id: UUID, db: DbSession, _: ManagerAccess
) -> ServiceDetailRead:
    service = await ServiceService(db).toggle_featured(service_id)
    return _to_detail(service)


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(service_id: UUID, db: DbSession, _: AdminAccess) -> None:
    await ServiceService(db).soft_delete(service_id)


# --- Service Options nested endpoints ----------------------------------------


@router.get("/{service_id}/options", response_model=list[ServiceOptionRead])
async def list_options(service_id: UUID, db: DbSession, _: ReadAccess) -> list[ServiceOptionRead]:
    options = await ServiceOptionService(db).list(service_id)
    return [ServiceOptionRead.model_validate(o) for o in options]


@router.post(
    "/{service_id}/options",
    response_model=ServiceOptionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_option(
    service_id: UUID,
    payload: ServiceOptionCreate,
    db: DbSession,
    _: ManagerAccess,
) -> ServiceOptionRead:
    option = await ServiceOptionService(db).create(service_id, payload)
    return ServiceOptionRead.model_validate(option)


@router.post("/{service_id}/options/reorder", response_model=ReorderResponse)
async def reorder_options(
    service_id: UUID,
    payload: ReorderRequest,
    db: DbSession,
    _: ManagerAccess,
) -> ReorderResponse:
    updated = await ServiceOptionService(db).reorder(service_id, payload)
    return ReorderResponse(updated=updated)


@router.patch("/{service_id}/options/{option_id}", response_model=ServiceOptionRead)
async def update_option(
    service_id: UUID,
    option_id: UUID,
    payload: ServiceOptionUpdate,
    db: DbSession,
    _: ManagerAccess,
) -> ServiceOptionRead:
    option = await ServiceOptionService(db).update(service_id, option_id, payload)
    return ServiceOptionRead.model_validate(option)


@router.delete(
    "/{service_id}/options/{option_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_option(service_id: UUID, option_id: UUID, db: DbSession, _: ManagerAccess) -> None:
    await ServiceOptionService(db).delete(service_id, option_id)


# --- Public router -----------------------------------------------------------

# Slug pattern: lowercase letters, digits, single hyphens (no leading/trailing
# dash). Matches what GameCreate / ServiceCreate accept on the admin side, so
# any slug a public client passes mirrors a value the admin could store.
_PUBLIC_SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

public_router = APIRouter(prefix="/public/services", tags=["public"])


@public_router.get("", response_model=list[PublicServiceRead])
async def list_public_services(
    db: DbSession,
    game: Annotated[
        str | None,
        Query(
            description="Game slug",
            pattern=_PUBLIC_SLUG_PATTERN,
            max_length=100,
        ),
    ] = None,
    platform: Annotated[Platform | None, Query()] = None,
    featured: Annotated[bool | None, Query()] = None,
    page: Annotated[int, Query(ge=1, le=10000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[PublicServiceRead]:
    services = await ServiceService(db).list_public(
        game_slug=game, platform=platform, featured=featured
    )
    start = (page - 1) * page_size
    return [PublicServiceRead.model_validate(s) for s in services[start : start + page_size]]


@public_router.get("/{slug}", response_model=PublicServiceRead)
async def get_public_service(
    slug: Annotated[str, Path(pattern=_PUBLIC_SLUG_PATTERN, max_length=150)],
    db: DbSession,
) -> PublicServiceRead:
    service = await ServiceService(db).get_public(slug)
    return PublicServiceRead.model_validate(service)
