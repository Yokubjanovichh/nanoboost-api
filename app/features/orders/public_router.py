import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.core.config import settings
from app.core.dependencies import DbSession
from app.features.orders.public_schemas import (
    PublicOrderCreate,
    PublicOrderResponse,
)
from app.features.orders.public_service import PublicOrderService
from app.shared.payments import get_payment_provider

logger = logging.getLogger("nanoboost.public_orders")

public_router = APIRouter(prefix="/public/orders", tags=["public"])


@public_router.post("", response_model=PublicOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_public_order(
    payload: PublicOrderCreate,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> PublicOrderResponse:
    order = await PublicOrderService(db).create(payload, background_tasks=background_tasks)

    checkout_url: str | None = None
    provider = get_payment_provider(payload.payment_method)
    if provider is not None:
        return_url = f"{settings.PUBLIC_SITE_URL}/payment-success?order={order.order_number}"
        cancel_url = f"{settings.PUBLIC_SITE_URL}/payment-cancelled?order={order.order_number}"
        try:
            session = await provider.create_session(
                order, return_url=return_url, cancel_url=cancel_url
            )
        except NotImplementedError as exc:
            # Phase 1 skeleton — provider class is wired but credentials/
            # implementation arrive in Phase 4. Surface as 503 so the
            # frontend can show a clear "try another method" CTA.
            logger.warning(
                "Payment provider %s not configured yet (order=%s): %s",
                provider.name,
                order.order_number,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Payment provider not yet configured",
            ) from exc

        order.payment_provider = session.provider
        order.payment_session_id = session.session_id
        order.payment_checkout_url = session.checkout_url
        order.payment_status_updated_at = datetime.now(UTC)
        await db.commit()
        checkout_url = session.checkout_url

    return PublicOrderResponse(
        order_number=order.order_number,
        status=order.status,
        final_total_usd=float(order.final_total_usd),
        display_currency=order.display_currency,
        created_at=order.created_at,
        checkout_url=checkout_url,
    )
