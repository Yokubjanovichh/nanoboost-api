"""Public order creation + status lookup + auto-cancel sweep."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.constants import DisplayCurrency, OrderStatus, PaymentMethod
from app.features.clients.models import Client
from app.features.orders.models import Order
from app.features.orders.service import OrderService

# --- Public POST validation ------------------------------------------------


@pytest.mark.asyncio
async def test_create_rejects_empty_items(client_with_db):
    res = await client_with_db.post(
        "/api/v1/public/orders",
        json={
            "email": "buyer@example.com",
            "payment_method": "card_ecomtrade24",
            "items": [],  # min_length=1
        },
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_bad_email(client_with_db):
    res = await client_with_db.post(
        "/api/v1/public/orders",
        json={
            "email": "not-an-email",
            "payment_method": "card_ecomtrade24",
            "items": [
                {
                    "service_id": "00000000-0000-0000-0000-000000000000",
                    "option_id": "00000000-0000-0000-0000-000000000000",
                    "quantity": 1,
                }
            ],
        },
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_invalid_payment_method(client_with_db):
    res = await client_with_db.post(
        "/api/v1/public/orders",
        json={
            "email": "buyer@example.com",
            "payment_method": "bitcoin",  # not in PaymentMethod enum
            "items": [
                {
                    "service_id": "00000000-0000-0000-0000-000000000000",
                    "option_id": "00000000-0000-0000-0000-000000000000",
                    "quantity": 1,
                }
            ],
        },
    )
    assert res.status_code == 422


# --- Public status endpoint -------------------------------------------------


@pytest.mark.asyncio
async def test_status_returns_404_for_missing(client_with_db):
    res = await client_with_db.get("/api/v1/public/orders/NB-MISSING/status")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_status_returns_pii_free_payload(client_with_db, db_session):
    client = Client(email="customer@test.io", telegram="@cust")
    db_session.add(client)
    await db_session.flush()
    order = Order(
        order_number="NB-12345",
        client_id=client.id,
        status=OrderStatus.PAID,
        payment_method=PaymentMethod.CARD_ECOMTRADE24,
        display_currency=DisplayCurrency.USD,
        subtotal_usd=Decimal("10"),
        final_total_usd=Decimal("10"),
        paid_at=datetime.now(UTC),
    )
    db_session.add(order)
    await db_session.commit()

    res = await client_with_db.get("/api/v1/public/orders/NB-12345/status")
    assert res.status_code == 200
    body = res.json()
    assert body["order_number"] == "NB-12345"
    assert body["status"] == "paid"
    # PII-free: no email, telegram, or client info should leak.
    assert "email" not in body
    assert "telegram" not in body
    assert "client" not in body


# --- Auto-cancel sweep ------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_stale_pending_targets_old_pendings(db_session):
    client = Client(email="auto@test.io")
    db_session.add(client)
    await db_session.flush()
    now = datetime.now(UTC)

    def _make(num, status, created_at, notes=None):
        return Order(
            order_number=num,
            client_id=client.id,
            status=status,
            payment_method=PaymentMethod.CARD_ECOMTRADE24,
            display_currency=DisplayCurrency.USD,
            subtotal_usd=Decimal("10"),
            final_total_usd=Decimal("10"),
            created_at=created_at,
            admin_notes=notes,
        )

    db_session.add_all(
        [
            _make("NB-OLD-1", OrderStatus.PENDING, now - timedelta(hours=25)),
            _make("NB-OLD-2", OrderStatus.PENDING, now - timedelta(hours=30), "manual"),
            _make("NB-FRESH", OrderStatus.PENDING, now - timedelta(hours=1)),
            _make("NB-PAID", OrderStatus.PAID, now - timedelta(hours=48), "paid note"),
        ]
    )
    await db_session.commit()

    cancelled = await OrderService(db_session).cancel_stale_pending(hours=24)
    assert cancelled == 2

    # Re-fetch and verify per-row outcome.
    db_session.expire_all()
    from sqlalchemy import select

    rows = (await db_session.execute(select(Order))).scalars().all()
    by_num = {o.order_number: o for o in rows}

    assert by_num["NB-OLD-1"].status == OrderStatus.CANCELLED
    assert by_num["NB-OLD-1"].cancelled_at is not None
    assert "Auto-cancelled" in by_num["NB-OLD-1"].admin_notes

    # Manual note preserved + auto note appended.
    assert by_num["NB-OLD-2"].admin_notes.startswith("manual")
    assert "Auto-cancelled" in by_num["NB-OLD-2"].admin_notes

    # Untouched.
    assert by_num["NB-FRESH"].status == OrderStatus.PENDING
    assert by_num["NB-PAID"].status == OrderStatus.PAID
    assert by_num["NB-PAID"].admin_notes == "paid note"


@pytest.mark.asyncio
async def test_cancel_stale_pending_idempotent(db_session):
    client = Client(email="idem@test.io")
    db_session.add(client)
    await db_session.flush()
    db_session.add(
        Order(
            order_number="NB-OLD",
            client_id=client.id,
            status=OrderStatus.PENDING,
            payment_method=PaymentMethod.CARD_ECOMTRADE24,
            display_currency=DisplayCurrency.USD,
            subtotal_usd=Decimal("1"),
            final_total_usd=Decimal("1"),
            created_at=datetime.now(UTC) - timedelta(hours=48),
        )
    )
    await db_session.commit()

    first = await OrderService(db_session).cancel_stale_pending(hours=24)
    second = await OrderService(db_session).cancel_stale_pending(hours=24)
    assert first == 1
    assert second == 0
