from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import DbSession
from app.core.permissions import require_any_authenticated, require_manager_or_above
from app.features.clients.schemas import ClientRead, ClientUpdate, ClientWithStats
from app.features.clients.service import ClientService
from app.features.orders.schemas import OrderRead
from app.features.users.models import User
from app.shared.pagination import Paginated, PaginationDep, paginate

router = APIRouter(prefix="/clients", tags=["clients"])

ReadAccess = Annotated[User, Depends(require_any_authenticated)]
ManagerAccess = Annotated[User, Depends(require_manager_or_above)]


@router.get("", response_model=Paginated[ClientRead])
async def list_clients(
    db: DbSession,
    _: ReadAccess,
    page: PaginationDep,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> Paginated[ClientRead]:
    items, total = await ClientService(db).list(
        limit=page.limit, offset=page.offset, search=search
    )
    return paginate(
        [ClientRead.model_validate(c) for c in items], total=total, params=page
    )


@router.get("/{client_id}", response_model=ClientWithStats)
async def get_client(
    client_id: UUID, db: DbSession, _: ReadAccess
) -> ClientWithStats:
    return await ClientService(db).get_with_stats(client_id)


@router.get("/{client_id}/orders", response_model=Paginated[OrderRead])
async def list_client_orders(
    client_id: UUID,
    db: DbSession,
    _: ReadAccess,
    page: PaginationDep,
) -> Paginated[OrderRead]:
    items, total = await ClientService(db).list_orders(
        client_id, limit=page.limit, offset=page.offset
    )
    return paginate(
        [OrderRead.model_validate(o) for o in items], total=total, params=page
    )


@router.patch("/{client_id}", response_model=ClientRead)
async def update_client(
    client_id: UUID,
    payload: ClientUpdate,
    db: DbSession,
    _: ManagerAccess,
) -> ClientRead:
    client = await ClientService(db).update(client_id, payload)
    return ClientRead.model_validate(client)
