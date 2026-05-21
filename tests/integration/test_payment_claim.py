"""POST /api/v1/public/orders/{number}/claim-payment.

Manual-payment fulfillment: customer pays into our wallet/PayPal outside
the API, then clicks "I have paid" on the success page. The endpoint
sets `payment_claimed_at` and pings the admin via Telegram so they can
verify and flip status → PAID by hand.

Status stays PENDING throughout — only admin-side verification advances
it. The claim is purely a customer-driven signal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core.constants import DisplayCurrency, OrderStatus, PaymentMethod
from app.features.clients.models import Client
from app.features.orders.models import Order


async def _make_order(
    db,
    *,
    number: str,
    payment_method: PaymentMethod,
    status: OrderStatus = OrderStatus.PENDING,
    payment_claimed_at: datetime | None = None,
) -> Order:
    client = Client(email=f"{number}@test.io", telegram=f"@{number}", whatsapp="+15551234567")
    db.add(client)
    await db.flush()
    order = Order(
        order_number=number,
        client_id=client.id,
        status=status,
        payment_method=payment_method,
        display_currency=DisplayCurrency.USD,
        subtotal_usd=Decimal("100"),
        final_total_usd=Decimal("100"),
        final_total_eur=Decimal("90"),
        payment_claimed_at=payment_claimed_at,
    )
    db.add(order)
    await db.commit()
    return order


# --- Happy paths ---------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_payment_for_paypal_order(client_with_db, db_session):
    await _make_order(db_session, number="NB-PP-1", payment_method=PaymentMethod.PAYPAL)

    res = await client_with_db.post("/api/v1/public/orders/NB-PP-1/claim-payment")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["order_number"] == "NB-PP-1"
    assert body["status"] == "pending"
    assert body["payment_claimed_at"] is not None


@pytest.mark.asyncio
async def test_claim_payment_for_usdt_order(client_with_db, db_session):
    await _make_order(db_session, number="NB-USDT-1", payment_method=PaymentMethod.USDT_TRC20)

    res = await client_with_db.post("/api/v1/public/orders/NB-USDT-1/claim-payment")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "pending"
    assert body["payment_claimed_at"] is not None


# --- Validation paths ----------------------------------------------------


@pytest.mark.asyncio
async def test_claim_payment_rejects_hosted_checkout_method(client_with_db, db_session):
    """EcomTrade24 (and any future hosted-checkout provider) goes through
    the webhook flow — claiming here would race the webhook."""
    await _make_order(db_session, number="NB-CARD-1", payment_method=PaymentMethod.CARD_ECOMTRADE24)

    res = await client_with_db.post("/api/v1/public/orders/NB-CARD-1/claim-payment")
    assert res.status_code == 400
    assert "PayPal" in res.json()["detail"] or "USDT" in res.json()["detail"]


@pytest.mark.asyncio
async def test_claim_payment_returns_404_for_unknown_order(client_with_db):
    res = await client_with_db.post("/api/v1/public/orders/NB-MISSING/claim-payment")
    assert res.status_code == 404


# --- Idempotency ---------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_payment_is_idempotent(client_with_db, db_session, monkeypatch):
    """Replaying the call returns the original `payment_claimed_at` and
    does NOT re-notify Telegram — that's the contract for the FE retry
    case (offline blip, double-click)."""
    # Patch the binding the router actually uses, not the original module.
    from app.features.orders import public_router

    notify_calls = 0

    class _CountingNotifier:
        async def notify_payment_claim(self, order):
            nonlocal notify_calls
            notify_calls += 1

    monkeypatch.setattr(public_router, "get_order_notifier", lambda: _CountingNotifier())

    await _make_order(db_session, number="NB-PP-IDEM", payment_method=PaymentMethod.PAYPAL)

    first = await client_with_db.post("/api/v1/public/orders/NB-PP-IDEM/claim-payment")
    second = await client_with_db.post("/api/v1/public/orders/NB-PP-IDEM/claim-payment")

    assert first.status_code == 200
    assert second.status_code == 200
    # Same timestamp on both — the second call did not overwrite.
    assert first.json()["payment_claimed_at"] == second.json()["payment_claimed_at"]
    # Exactly one Telegram alert across both calls.
    assert notify_calls == 1, f"expected 1 notify, got {notify_calls}"


@pytest.mark.asyncio
async def test_claim_payment_for_paid_order_returns_state_unchanged(client_with_db, db_session):
    """Admin already flipped → PAID before the customer clicked. Return
    the current state without re-triggering the claim flow."""
    await _make_order(
        db_session,
        number="NB-PP-PAID",
        payment_method=PaymentMethod.PAYPAL,
        status=OrderStatus.PAID,
    )

    res = await client_with_db.post("/api/v1/public/orders/NB-PP-PAID/claim-payment")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "paid"
    # No claim was ever filed → still NULL.
    assert body["payment_claimed_at"] is None


# --- Persistence sanity --------------------------------------------------


@pytest.mark.asyncio
async def test_claim_payment_persists_timestamp(client_with_db, db_session):
    """Sanity: the timestamp survives a DB round-trip and is timezone-aware."""
    from sqlalchemy import select

    await _make_order(db_session, number="NB-PP-PERSIST", payment_method=PaymentMethod.PAYPAL)

    before = datetime.now(UTC)
    res = await client_with_db.post("/api/v1/public/orders/NB-PP-PERSIST/claim-payment")
    after = datetime.now(UTC)
    assert res.status_code == 200

    db_session.expire_all()
    stored = (
        await db_session.execute(select(Order).where(Order.order_number == "NB-PP-PERSIST"))
    ).scalar_one()
    assert stored.payment_claimed_at is not None
    # Tolerate the SQLite drop-to-naive case — compare against UTC-naive bounds.
    ts = stored.payment_claimed_at
    if ts.tzinfo is None:
        before = before.replace(tzinfo=None)
        after = after.replace(tzinfo=None)
    assert before <= ts <= after
