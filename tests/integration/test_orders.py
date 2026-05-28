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
                    "service_slug": "some-service",
                    "option_id": "00000000-0000-0000-0000-000000000000",
                    "qty": 1,
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
                    "service_slug": "some-service",
                    "option_id": "00000000-0000-0000-0000-000000000000",
                    "qty": 1,
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
        final_total_eur=Decimal("9"),
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
    # FAZA 4 fields: EUR snapshot + polling-friendly timestamp.
    assert body["final_total_eur"] == 9.0
    assert body["last_updated_at"] is not None


# --- Slug-based item contract (HOTFIX) -------------------------------------


@pytest.mark.asyncio
async def test_create_rejects_unknown_service_slug_with_404(client_with_db):
    """Unknown slug → 404 (NotFoundError), not 422. The slug isn't a
    schema violation — it's a missing resource."""
    res = await client_with_db.post(
        "/api/v1/public/orders",
        json={
            "email": "buyer@example.com",
            "payment_method": "card_ecomtrade24",
            "items": [
                {
                    "service_slug": "does-not-exist",
                    "option_id": "00000000-0000-0000-0000-000000000000",
                    "qty": 1,
                }
            ],
        },
    )
    assert res.status_code == 404
    assert "does-not-exist" in res.json()["detail"]


@pytest.mark.asyncio
async def test_create_rejects_empty_service_slug_with_422(client_with_db):
    """Empty slug fails at the schema layer (min_length=1) before the
    DB lookup. Pydantic 422, not 404."""
    res = await client_with_db.post(
        "/api/v1/public/orders",
        json={
            "email": "buyer@example.com",
            "payment_method": "card_ecomtrade24",
            "items": [
                {
                    "service_slug": "",
                    "option_id": "00000000-0000-0000-0000-000000000000",
                    "qty": 1,
                }
            ],
        },
    )
    assert res.status_code == 422


# --- EUR aggregate + discount (FAZA 4) -------------------------------------


@pytest.mark.asyncio
async def test_create_persists_eur_snapshot_and_discount(client_with_db, db_session):
    """USDT path gets 5% off, populates final_total_eur from per-item EUR
    prices, and surfaces both in the POST response."""
    from sqlalchemy import select

    from app.core.constants import GameStatus, Platform
    from app.features.games.models import Game
    from app.features.services.models import Service, ServiceOption

    game = Game(
        slug="gta-v",
        name="GTA V",
        sort_order=0,
        status=GameStatus.ACTIVE,
        is_deleted=False,
    )
    db_session.add(game)
    await db_session.flush()
    svc = Service(
        game_id=game.id,
        slug="gta-cash",
        title="GTA Cash",
        platform=Platform.PS,
        description=["x"],
        what_you_get=[],
        sections=[],
        is_active=True,
        is_deleted=False,
        sort_order=0,
    )
    db_session.add(svc)
    await db_session.flush()
    option = ServiceOption(
        service_id=svc.id,
        label="100m",
        price_usd=Decimal("100.00"),
        price_eur=Decimal("90.00"),
        is_default=True,
        sort_order=0,
    )
    db_session.add(option)
    await db_session.commit()

    res = await client_with_db.post(
        "/api/v1/public/orders",
        json={
            "email": "eur@test.io",
            "payment_method": "usdt_trc20",
            "display_currency": "EUR",
            "items": [
                {
                    "service_slug": svc.slug,
                    "option_id": str(option.id),
                    "qty": 2,
                }
            ],
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    # subtotal_usd = 200, USDT 5% off → discount 10, final 190
    assert body["final_total_usd"] == 190.0
    assert body["discount_amount_usd"] == 10.0
    # subtotal_eur = 180, 5% off → final_eur 171
    assert body["final_total_eur"] == 171.0
    assert body["display_currency"] == "EUR"

    # Snapshot persisted to the row, not computed on read.
    stored = (
        await db_session.execute(select(Order).where(Order.order_number == body["order_number"]))
    ).scalar_one()
    assert stored.final_total_eur == Decimal("171.00")


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


# --- Extended fulfilment pipeline (migration 0014) -------------------------


async def _seed_paid_order(db_session, order_number: str) -> Order:
    client = Client(email=f"{order_number}@test.io")
    db_session.add(client)
    await db_session.flush()
    order = Order(
        order_number=order_number,
        client_id=client.id,
        status=OrderStatus.PAID,
        payment_method=PaymentMethod.CARD_ECOMTRADE24,
        display_currency=DisplayCurrency.USD,
        subtotal_usd=Decimal("10"),
        final_total_usd=Decimal("10"),
        final_total_eur=Decimal("9"),
        paid_at=datetime.now(UTC),
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    return order


@pytest.mark.asyncio
async def test_change_status_paid_to_awaiting_booster_sets_timestamp(db_session):
    from app.features.orders.schemas import OrderStatusUpdate

    order = await _seed_paid_order(db_session, "NB-PIPE-1")
    assert order.awaiting_booster_at is None

    service = OrderService(db_session)
    updated = await service.change_status(
        order.id, OrderStatusUpdate(status=OrderStatus.AWAITING_BOOSTER)
    )

    assert updated.status == OrderStatus.AWAITING_BOOSTER
    assert updated.awaiting_booster_at is not None


@pytest.mark.asyncio
async def test_change_status_full_fulfilment_pipeline(db_session):
    """paid → awaiting_booster → in_progress → booster_completed
    → delivered_to_client → completed. Each new stage stamps its own
    timestamp; in_progress is intentionally silent (no column)."""
    from app.features.orders.schemas import OrderStatusUpdate

    order = await _seed_paid_order(db_session, "NB-PIPE-2")
    svc = OrderService(db_session)

    pipeline = [
        (OrderStatus.AWAITING_BOOSTER, "awaiting_booster_at"),
        (OrderStatus.IN_PROGRESS, None),  # no timestamp column by design
        (OrderStatus.BOOSTER_COMPLETED, "booster_completed_at"),
        (OrderStatus.DELIVERED_TO_CLIENT, "delivered_to_client_at"),
        (OrderStatus.COMPLETED, "completed_at"),
    ]

    for target, ts_field in pipeline:
        updated = await svc.change_status(order.id, OrderStatusUpdate(status=target))
        assert updated.status == target
        if ts_field is not None:
            assert getattr(updated, ts_field) is not None, (
                f"{ts_field} should be set on transition to {target.value}"
            )


async def _seed_service_with_discount(db_session, **option_kwargs):
    """Create a Game + Service + single ServiceOption row with the given
    discount fields. Returns the option_id and service_slug."""
    from app.core.constants import GameStatus, Platform
    from app.features.games.models import Game
    from app.features.services.models import Service, ServiceOption

    game = Game(slug="dg", name="Discount Game", sort_order=0, status=GameStatus.ACTIVE)
    db_session.add(game)
    await db_session.flush()
    svc = Service(
        game_id=game.id,
        slug="discounted-service",
        title="Discounted",
        platform=Platform.PS,
        description=["x"],
        what_you_get=[],
        sections=[],
        is_active=True,
        is_deleted=False,
        sort_order=0,
    )
    db_session.add(svc)
    await db_session.flush()
    opt = ServiceOption(
        service_id=svc.id,
        label="Standard",
        price_usd=Decimal("100"),
        price_eur=Decimal("90"),
        is_default=True,
        sort_order=0,
        **option_kwargs,
    )
    db_session.add(opt)
    await db_session.commit()
    await db_session.refresh(opt)
    return svc.slug, opt.id


async def _fetch_order_and_item(db_session, order_number: str):
    """Public POST response is intentionally lean — pull the full order
    row + its single item from the DB for assertions."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.features.orders.models import Order

    res = await db_session.execute(
        select(Order).options(selectinload(Order.items)).where(Order.order_number == order_number)
    )
    order = res.scalar_one()
    return order, order.items[0]


@pytest.mark.asyncio
async def test_public_order_applies_option_percent_discount(client_with_db, db_session):
    slug, option_id = await _seed_service_with_discount(db_session, discount_percent=20)
    res = await client_with_db.post(
        "/api/v1/public/orders",
        json={
            "email": "buyer@test.io",
            "payment_method": "card_ecomtrade24",
            "items": [{"service_slug": slug, "option_id": str(option_id), "qty": 2}],
        },
    )
    assert res.status_code == 201, res.text
    # Card path has no order-level discount, so final equals subtotal.
    # 100 USD * 0.80 = 80 per unit; qty=2 -> 160 subtotal.
    assert res.json()["final_total_usd"] == 160.0

    order, item = await _fetch_order_and_item(db_session, res.json()["order_number"])
    assert order.subtotal_usd == Decimal("160.00")
    assert order.discount_percent == 0
    assert item.unit_price_usd == Decimal("80.00")
    assert item.total_price_usd == Decimal("160.00")


@pytest.mark.asyncio
async def test_public_order_applies_option_amount_discount(client_with_db, db_session):
    slug, option_id = await _seed_service_with_discount(
        db_session,
        discount_amount_usd=Decimal("15"),
        discount_amount_eur=Decimal("12"),
    )
    res = await client_with_db.post(
        "/api/v1/public/orders",
        json={
            "email": "buyer@test.io",
            "payment_method": "card_ecomtrade24",
            "items": [{"service_slug": slug, "option_id": str(option_id), "qty": 1}],
        },
    )
    assert res.status_code == 201

    _, item = await _fetch_order_and_item(db_session, res.json()["order_number"])
    assert item.unit_price_usd == Decimal("85.00")
    assert item.unit_price_eur == Decimal("78.00")


@pytest.mark.asyncio
async def test_public_order_usdt_stacks_on_item_discount(client_with_db, db_session):
    """Item-level percent first, then order-level USDT 5% on the already
    discounted subtotal. 100 -> 80 (item 20%) -> 76 (USDT 5% of 80)."""
    slug, option_id = await _seed_service_with_discount(db_session, discount_percent=20)
    res = await client_with_db.post(
        "/api/v1/public/orders",
        json={
            "email": "buyer@test.io",
            "payment_method": "usdt_trc20",
            "items": [{"service_slug": slug, "option_id": str(option_id), "qty": 1}],
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["final_total_usd"] == 76.0  # 80 - 5%

    order, item = await _fetch_order_and_item(db_session, res.json()["order_number"])
    assert item.unit_price_usd == Decimal("80.00")  # already discounted
    assert order.subtotal_usd == Decimal("80.00")  # built from discounted units
    assert order.discount_percent == 5  # USDT order-level
    assert order.final_total_usd == Decimal("76.00")


@pytest.mark.asyncio
async def test_public_order_no_discount_unchanged(client_with_db, db_session):
    """Regression guard: an option without discount fields prices the
    same as it did before migration 0015."""
    slug, option_id = await _seed_service_with_discount(db_session)
    res = await client_with_db.post(
        "/api/v1/public/orders",
        json={
            "email": "buyer@test.io",
            "payment_method": "card_ecomtrade24",
            "items": [{"service_slug": slug, "option_id": str(option_id), "qty": 1}],
        },
    )
    assert res.status_code == 201
    _, item = await _fetch_order_and_item(db_session, res.json()["order_number"])
    assert item.unit_price_usd == Decimal("100.00")
    assert item.unit_price_eur == Decimal("90.00")


@pytest.mark.asyncio
async def test_public_order_snapshot_records_discount_audit(client_with_db, db_session):
    """OrderItem.service_snapshot must capture the original price and
    discount fields at order time so a later price change on the live
    option can't rewrite history."""
    slug, option_id = await _seed_service_with_discount(db_session, discount_percent=20)
    res = await client_with_db.post(
        "/api/v1/public/orders",
        json={
            "email": "buyer@test.io",
            "payment_method": "card_ecomtrade24",
            "items": [{"service_slug": slug, "option_id": str(option_id), "qty": 1}],
        },
    )
    assert res.status_code == 201

    _, item = await _fetch_order_and_item(db_session, res.json()["order_number"])
    snap = item.service_snapshot
    assert snap["option"]["original_price_usd"] == "100.00"
    assert snap["option"]["original_price_eur"] == "90.00"
    # Decimal serialized as string for JSONB portability.
    assert snap["option"]["discount_percent"] == "20.000"
    assert snap["option"]["discount_amount_usd"] is None


@pytest.mark.asyncio
async def test_change_status_skip_stage_rejected(db_session):
    """Cannot skip from PAID directly to IN_PROGRESS — must traverse
    AWAITING_BOOSTER first. Guards the new pipeline order."""
    from app.core.exceptions import InvalidStatusTransitionError
    from app.features.orders.schemas import OrderStatusUpdate

    order = await _seed_paid_order(db_session, "NB-PIPE-3")
    svc = OrderService(db_session)
    with pytest.raises(InvalidStatusTransitionError):
        await svc.change_status(order.id, OrderStatusUpdate(status=OrderStatus.IN_PROGRESS))
