from fastapi import APIRouter, BackgroundTasks, status

from app.core.dependencies import DbSession
from app.features.orders.public_schemas import (
    PublicOrderCreate,
    PublicOrderResponse,
)
from app.features.orders.public_service import PublicOrderService

public_router = APIRouter(prefix="/public/orders", tags=["public"])


@public_router.post("", response_model=PublicOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_public_order(
    payload: PublicOrderCreate,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> PublicOrderResponse:
    order = await PublicOrderService(db).create(payload, background_tasks=background_tasks)
    return PublicOrderResponse(
        order_number=order.order_number,
        status=order.status,
        final_total_usd=float(order.final_total_usd),
        display_currency=order.display_currency,
        created_at=order.created_at,
    )
