"""Payment provider webhook receivers.

Per-provider endpoints keep signature verification, payload shape and
idempotency table writes local — easier to reason about than a single
multiplexed handler.

Public (no auth). Cloudflare rate-limiting rule guards against floods.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from sqlalchemy import select

from app.core.constants import OrderStatus, PaymentMethod
from app.core.dependencies import DbSession
from app.features.orders.models import Order
from app.features.payments.models import PaymentWebhookEvent
from app.shared.notifications import get_order_notifier
from app.shared.payments import get_payment_provider
from app.shared.payments.ecomtrade24 import PROVIDER_NAME as ECOMTRADE24_NAME

logger = logging.getLogger("nanoboost.payments.webhook")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/ecomtrade24", status_code=status.HTTP_200_OK)
async def ecomtrade24_webhook(
    request: Request,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> dict:
    raw_body = await request.body()
    signature = request.headers.get("X-EcomTrade24-Signature") or request.headers.get(
        "X-Signature", ""
    )

    provider = get_payment_provider(PaymentMethod.CARD_ECOMTRADE24)
    if provider is None:  # registry misconfigured — bail out
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment provider not available",
        )

    if not provider.verify_webhook_signature(raw_body, signature):
        # Don't echo the reason — opaque 401 is harder to probe.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON payload",
        ) from exc

    try:
        event = provider.parse_webhook_event(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # Idempotency — composite PK (provider, event_id) is the natural key.
    existing = await db.get(PaymentWebhookEvent, (event.provider, event.event_id))
    if existing is not None:
        logger.info(
            "Duplicate webhook ignored: provider=%s event_id=%s",
            event.provider,
            event.event_id,
        )
        return {"status": "already_processed"}

    order: Order | None = None
    if event.order_id:
        order = (
            await db.execute(select(Order).where(Order.order_number == event.order_id))
        ).scalar_one_or_none()

    if order is not None and event.status == "paid" and order.status == OrderStatus.PENDING:
        now = datetime.now(UTC)
        old_status = order.status
        order.status = OrderStatus.PAID
        order.paid_at = now
        order.payment_status_updated_at = now
        background_tasks.add_task(
            get_order_notifier().notify_status_change,
            order,
            old_status,
            OrderStatus.PAID,
        )

    db.add(
        PaymentWebhookEvent(
            provider=event.provider,
            event_id=event.event_id,
            order_id=order.id if order else None,
            event_type=event.event_type,
            raw_payload=event.raw_payload,
        )
    )
    await db.commit()

    return {"status": "ok", "provider": ECOMTRADE24_NAME}
