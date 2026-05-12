from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.core.constants import OrderStatus, PaymentMethod
from app.core.dependencies import DbSession
from app.core.permissions import require_any_authenticated, require_manager_or_above
from app.features.orders.schemas import (
    OrderDetailRead,
    OrderRead,
    OrderStats,
    OrderStatusUpdate,
    OrderUpdate,
)
from app.features.orders.service import OrderService
from app.features.users.models import User
from app.shared.pagination import Paginated, PaginationDep, paginate

router = APIRouter(prefix="/orders", tags=["orders"])

ReadAccess = Annotated[User, Depends(require_any_authenticated)]
ManagerAccess = Annotated[User, Depends(require_manager_or_above)]


def _to_read(order, items_count: int) -> OrderRead:
    base = OrderRead.model_validate(order)
    return base.model_copy(update={"items_count": items_count})


def _to_detail(order) -> OrderDetailRead:
    base = OrderDetailRead.model_validate(order)
    return base.model_copy(update={"items_count": len(order.items)})


@router.get("/stats", response_model=OrderStats)
async def get_order_stats(db: DbSession, _: ReadAccess) -> OrderStats:
    return await OrderService(db).stats()


@router.get("", response_model=Paginated[OrderRead])
async def list_orders(
    db: DbSession,
    _: ReadAccess,
    page: PaginationDep,
    status: Annotated[OrderStatus | None, Query()] = None,
    client_id: Annotated[UUID | None, Query()] = None,
    payment_method: Annotated[PaymentMethod | None, Query()] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    sort: Annotated[str | None, Query()] = None,
) -> Paginated[OrderRead]:
    rows, total = await OrderService(db).list(
        limit=page.limit,
        offset=page.offset,
        status=status,
        client_id=client_id,
        payment_method=payment_method,
        date_from=date_from,
        date_to=date_to,
        search=search,
        sort=sort,
    )
    items = [_to_read(o, c) for o, c in rows]
    return paginate(items, total=total, params=page)


@router.get("/{order_id}", response_model=OrderDetailRead)
async def get_order(order_id: UUID, db: DbSession, _: ReadAccess) -> OrderDetailRead:
    order = await OrderService(db).get(order_id)
    return _to_detail(order)


@router.patch("/{order_id}", response_model=OrderDetailRead)
async def update_order(
    order_id: UUID,
    payload: OrderUpdate,
    db: DbSession,
    _: ManagerAccess,
) -> OrderDetailRead:
    order = await OrderService(db).update(order_id, payload)
    return _to_detail(order)


@router.patch("/{order_id}/status", response_model=OrderDetailRead)
async def change_order_status(
    order_id: UUID,
    payload: OrderStatusUpdate,
    db: DbSession,
    _: ManagerAccess,
    background_tasks: BackgroundTasks,
) -> OrderDetailRead:
    order = await OrderService(db).change_status(
        order_id, payload, background_tasks=background_tasks
    )
    return _to_detail(order)
