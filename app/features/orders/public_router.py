import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.constants import OrderStatus, PaymentMethod
from app.core.dependencies import DbSession
from app.core.exceptions import InvalidPaymentError, PaymentProviderError
from app.features.orders.models import Order
from app.features.orders.public_schemas import (
    PaymentClaimResponse,
    PublicOrderCreate,
    PublicOrderResponse,
    PublicOrderStatusResponse,
)
from app.features.orders.public_service import PublicOrderService
from app.shared.notifications import get_order_notifier
from app.shared.payments import get_payment_provider

# Methods where the buyer pushes money to our wallet/PayPal outside the
# API. The hosted-checkout providers (e.g. EcomTrade24) don't go through
# this endpoint — their webhook flips status → PAID directly.
_MANUAL_PAYMENT_METHODS = frozenset({PaymentMethod.PAYPAL, PaymentMethod.USDT_TRC20})

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
        except (InvalidPaymentError, PaymentProviderError):
            # Both already carry user-friendly Russian detail + correct
            # HTTP status (400 / 502). Let FastAPI return them as-is.
            raise
        except NotImplementedError as exc:
            # Reached only if a future provider is wired up but not yet
            # implemented. Phase 4 EcomTrade24 is implemented now; this
            # branch stays as a safety net for the next provider that
            # arrives skeleton-first.
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
        except Exception as exc:
            # Anything unexpected from a provider becomes a generic 502 —
            # we don't leak stack traces or upstream payload shape to the
            # customer. Full traceback hits the logs via exc_info.
            logger.exception(
                "Payment provider %s raised unexpectedly (order=%s)",
                provider.name,
                order.order_number,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Ошибка платёжной системы. Попробуйте позже.",
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
        final_total_eur=float(order.final_total_eur) if order.final_total_eur is not None else None,
        discount_amount_usd=float(order.discount_amount_usd),
        display_currency=order.display_currency,
        created_at=order.created_at,
        checkout_url=checkout_url,
    )


@public_router.post(
    "/{order_number}/claim-payment",
    response_model=PaymentClaimResponse,
    status_code=status.HTTP_200_OK,
)
async def claim_payment(
    order_number: str,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> PaymentClaimResponse:
    """Customer signals "I have paid" for a manual-payment order.

    Sets `payment_claimed_at` and pings the admin via Telegram so they
    can verify the wallet/PayPal balance and flip status → PAID.

    Idempotent — replaying the call returns the original timestamp and
    skips the notification. Only PENDING orders accept new claims;
    terminal-state orders return the current state unchanged.

    Public surface, no auth — `order_number` is the credential, same
    trust posture as the polling endpoint.
    """
    order = (
        await db.execute(
            select(Order)
            .options(selectinload(Order.client))
            .where(Order.order_number == order_number)
        )
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    if order.payment_method not in _MANUAL_PAYMENT_METHODS:
        # Hosted-checkout providers handle this via webhook. Surfacing
        # the buyer-side claim here would race the webhook and confuse
        # admins.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="claim-payment is only available for PayPal / USDT orders",
        )

    # Idempotency: already-claimed or terminal-state → return current
    # state without re-notifying. We also key off `payment_claimed_at`
    # specifically — status alone doesn't tell us whether the alert
    # already fired (admin could have flipped → PAID without a claim
    # ever being filed).
    if order.payment_claimed_at is not None or order.status != OrderStatus.PENDING:
        return PaymentClaimResponse(
            order_number=order.order_number,
            status=order.status,
            payment_claimed_at=order.payment_claimed_at,
        )

    now = datetime.now(UTC)
    order.payment_claimed_at = now
    # Status stays PENDING — admin verification is the gate to PAID.
    await db.commit()
    await db.refresh(order, ["payment_claimed_at"])

    background_tasks.add_task(get_order_notifier().notify_payment_claim, order)

    return PaymentClaimResponse(
        order_number=order.order_number,
        status=order.status,
        payment_claimed_at=order.payment_claimed_at,
    )


@public_router.get(
    "/{order_number}/status",
    response_model=PublicOrderStatusResponse,
)
async def get_public_order_status(
    order_number: str,
    db: DbSession,
) -> PublicOrderStatusResponse:
    """Polled by the payment-success page after the customer returns from
    the hosted checkout. Public — order_number is the only credential, same
    trust posture as a Stripe/PayPal session reference. PII-free response.
    """
    order = (
        await db.execute(select(Order).where(Order.order_number == order_number))
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    # Prefer payment_status_updated_at (last gateway nudge) over the row-wide
    # updated_at — the latter ticks on every admin edit and would spuriously
    # invalidate the polling client's "no change" check.
    last_updated_at = order.payment_status_updated_at or order.updated_at
    return PublicOrderStatusResponse(
        order_number=order.order_number,
        status=order.status,
        paid_at=order.paid_at,
        final_total_usd=float(order.final_total_usd),
        final_total_eur=float(order.final_total_eur) if order.final_total_eur is not None else None,
        display_currency=order.display_currency,
        last_updated_at=last_updated_at,
    )
