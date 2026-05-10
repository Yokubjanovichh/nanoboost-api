from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    ORDER_STATUS_TRANSITIONS,
    DisplayCurrency,
    OrderStatus,
    PaymentMethod,
    UserRole,
)
from app.core.security import create_access_token, hash_password
from app.features.clients.models import Client
from app.features.orders.models import Order, OrderItem
from app.features.orders.schemas import OrderInternalCreate, OrderItemCreate
from app.features.orders.service import OrderService, assert_transition
from app.features.users.models import User

pytestmark = pytest.mark.asyncio


async def _seed_client(db: AsyncSession, **overrides) -> Client:
    defaults = {
        "email": "buyer@nanoboost.io",
        "discord": "buyer#1234",
        "telegram": None,
        "notes": None,
    }
    defaults.update(overrides)
    client = Client(**defaults)
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return client


async def _seed_order(
    db: AsyncSession,
    *,
    client: Client,
    items: int = 1,
    **overrides,
) -> Order:
    seq = 1000 + int(datetime.now(UTC).timestamp() * 1000) % 9000
    defaults = {
        "order_number": f"NB-20260507-{seq:04d}",
        "client_id": client.id,
        "status": OrderStatus.PENDING,
        "payment_method": PaymentMethod.PAYPAL,
        "display_currency": DisplayCurrency.USD,
        "subtotal_usd": Decimal("19.99"),
        "discount_amount_usd": Decimal("0"),
        "discount_percent": 0,
        "final_total_usd": Decimal("19.99"),
        "comment": None,
        "admin_notes": None,
    }
    defaults.update(overrides)
    order = Order(**defaults)
    for _ in range(items):
        order.items.append(
            OrderItem(
                option_label="20 million",
                quantity=1,
                unit_price_usd=Decimal("19.99"),
                unit_price_eur=Decimal("16.99"),
                total_price_usd=Decimal("19.99"),
                total_price_eur=Decimal("16.99"),
                service_snapshot={
                    "slug": "gta-cash-ps",
                    "title": "GTA Cash PS",
                    "image_url": None,
                    "platform": None,
                    "game_slug": None,
                },
            )
        )
    db.add(order)
    await db.commit()
    return order


@pytest.fixture
async def manager_token(db_session: AsyncSession) -> str:
    user = User(
        email="manager-orders@nanoboost.io",
        password_hash=hash_password("Pass12345!"),
        role=UserRole.MANAGER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return create_access_token(user.id, user.role)


# --- LIST --------------------------------------------------------------------


async def test_list_empty(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.get("/api/v1/orders", headers=auth_header(superadmin_token))
    assert res.status_code == 200
    assert res.json()["total"] == 0


async def test_list_paginated(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    for i in range(3):
        await _seed_order(
            db_session, client=buyer, order_number=f"NB-20260507-100{i + 1}"
        )

    res = await client.get(
        "/api/v1/orders?page=1&page_size=2",
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    first = body["items"][0]
    assert first["items_count"] == 1
    # Client enrichment (Manager fix — frontend OrdersListPage):
    assert first["client"]["id"] == str(buyer.id)
    assert first["client"]["email"] == buyer.email
    assert first["client"]["discord"] == buyer.discord
    assert "telegram" in first["client"]


async def test_list_client_summary_omits_internal_fields(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    await _seed_order(db_session, client=buyer, order_number="NB-20260507-1001")

    res = await client.get(
        "/api/v1/orders", headers=auth_header(superadmin_token)
    )
    summary = res.json()["items"][0]["client"]
    # Compact summary — admin/internal fields not exposed in list response.
    for forbidden in ("notes", "whatsapp", "created_at", "updated_at"):
        assert forbidden not in summary


async def test_filter_by_status(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    await _seed_order(
        db_session, client=buyer, order_number="NB-20260507-1001", status=OrderStatus.PENDING
    )
    await _seed_order(
        db_session, client=buyer, order_number="NB-20260507-1002", status=OrderStatus.PAID
    )

    res = await client.get(
        "/api/v1/orders?status=paid", headers=auth_header(superadmin_token)
    )
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["status"] == "paid"


async def test_filter_by_client_id(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    c1 = await _seed_client(db_session, email="a@x.io")
    c2 = await _seed_client(db_session, email="b@x.io")
    await _seed_order(db_session, client=c1, order_number="NB-20260507-1001")
    await _seed_order(db_session, client=c2, order_number="NB-20260507-1002")

    res = await client.get(
        f"/api/v1/orders?client_id={c1.id}", headers=auth_header(superadmin_token)
    )
    assert res.json()["total"] == 1


async def test_filter_by_payment_method(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    await _seed_order(
        db_session,
        client=buyer,
        order_number="NB-20260507-1001",
        payment_method=PaymentMethod.PAYPAL,
    )
    await _seed_order(
        db_session,
        client=buyer,
        order_number="NB-20260507-1002",
        payment_method=PaymentMethod.USDT_TRC20,
    )

    res = await client.get(
        "/api/v1/orders?payment_method=usdt_trc20",
        headers=auth_header(superadmin_token),
    )
    assert res.json()["total"] == 1


async def test_search_by_order_number(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    await _seed_order(db_session, client=buyer, order_number="NB-20260507-1001")
    await _seed_order(db_session, client=buyer, order_number="NB-20260507-1002")

    res = await client.get(
        "/api/v1/orders?search=1002", headers=auth_header(superadmin_token)
    )
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["order_number"] == "NB-20260507-1002"


async def test_search_by_client_email(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    c1 = await _seed_client(db_session, email="alice@buy.io")
    c2 = await _seed_client(db_session, email="bob@buy.io")
    await _seed_order(db_session, client=c1, order_number="NB-20260507-1001")
    await _seed_order(db_session, client=c2, order_number="NB-20260507-1002")

    res = await client.get(
        "/api/v1/orders?search=alice", headers=auth_header(superadmin_token)
    )
    assert res.json()["total"] == 1


# --- DETAIL ------------------------------------------------------------------


async def test_get_detail_with_items(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    order = await _seed_order(
        db_session, client=buyer, order_number="NB-20260507-1001", items=2
    )
    res = await client.get(
        f"/api/v1/orders/{order.id}", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["client"]["email"] == "buyer@nanoboost.io"
    assert body["items_count"] == 2
    assert len(body["items"]) == 2


async def test_get_not_found(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.get(
        f"/api/v1/orders/{uuid4()}", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 404


# --- UPDATE ------------------------------------------------------------------


async def test_update_comment_and_admin_notes(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    order = await _seed_order(db_session, client=buyer, order_number="NB-20260507-1001")
    res = await client.patch(
        f"/api/v1/orders/{order.id}",
        json={"admin_notes": "VIP — priority", "comment": "rush"},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["admin_notes"] == "VIP — priority"
    assert body["comment"] == "rush"


# --- STATUS TRANSITIONS ------------------------------------------------------


async def test_status_change_triggers_notification(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
    monkeypatch,
) -> None:
    """PATCH /orders/{id}/status schedules a status-change notification."""
    from unittest.mock import AsyncMock

    captured = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.shared.notifications.OrderNotifier.notify_status_change",
        captured,
    )

    buyer = await _seed_client(db_session, email="status-notif@nano.io")
    order = await _seed_order(
        db_session, client=buyer, order_number="NB-20260509-9001"
    )
    res = await client.patch(
        f"/api/v1/orders/{order.id}/status",
        json={"status": "paid"},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    assert captured.await_count == 1


async def test_transition_pending_to_paid(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    order = await _seed_order(db_session, client=buyer, order_number="NB-20260507-1001")

    res = await client.patch(
        f"/api/v1/orders/{order.id}/status",
        json={"status": "paid"},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "paid"
    assert body["paid_at"] is not None


async def test_transition_paid_to_in_progress_to_completed(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    order = await _seed_order(
        db_session,
        client=buyer,
        order_number="NB-20260507-1001",
        status=OrderStatus.PAID,
    )

    r1 = await client.patch(
        f"/api/v1/orders/{order.id}/status",
        json={"status": "in_progress"},
        headers=auth_header(superadmin_token),
    )
    assert r1.status_code == 200

    r2 = await client.patch(
        f"/api/v1/orders/{order.id}/status",
        json={"status": "completed"},
        headers=auth_header(superadmin_token),
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "completed"
    assert r2.json()["completed_at"] is not None


async def test_transition_completed_to_refunded(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    order = await _seed_order(
        db_session,
        client=buyer,
        order_number="NB-20260507-1001",
        status=OrderStatus.COMPLETED,
    )
    res = await client.patch(
        f"/api/v1/orders/{order.id}/status",
        json={"status": "refunded"},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    assert res.json()["status"] == "refunded"
    assert res.json()["refunded_at"] is not None


async def test_invalid_transition_completed_to_paid(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    order = await _seed_order(
        db_session,
        client=buyer,
        order_number="NB-20260507-1001",
        status=OrderStatus.COMPLETED,
    )
    res = await client.patch(
        f"/api/v1/orders/{order.id}/status",
        json={"status": "paid"},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 409


async def test_invalid_transition_same_status(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    order = await _seed_order(
        db_session,
        client=buyer,
        order_number="NB-20260507-1001",
        status=OrderStatus.PAID,
    )
    res = await client.patch(
        f"/api/v1/orders/{order.id}/status",
        json={"status": "paid"},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 422


async def test_cancelled_is_terminal(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    order = await _seed_order(
        db_session,
        client=buyer,
        order_number="NB-20260507-1001",
        status=OrderStatus.CANCELLED,
    )
    res = await client.patch(
        f"/api/v1/orders/{order.id}/status",
        json={"status": "paid"},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 409


async def test_refunded_is_terminal(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    order = await _seed_order(
        db_session,
        client=buyer,
        order_number="NB-20260507-1001",
        status=OrderStatus.REFUNDED,
    )
    res = await client.patch(
        f"/api/v1/orders/{order.id}/status",
        json={"status": "completed"},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 409


async def test_state_machine_helper_rejects_unknown(db_session: AsyncSession) -> None:
    """assert_transition unit test (no DB but in async context)."""
    from app.core.exceptions import InvalidStatusTransitionError

    del db_session  # only present to satisfy the async fixture stack
    with pytest.raises(InvalidStatusTransitionError):
        assert_transition(OrderStatus.PENDING, OrderStatus.COMPLETED)


# --- PERMISSIONS -------------------------------------------------------------


async def test_status_update_viewer_forbidden(
    client: AsyncClient,
    db_session: AsyncSession,
    viewer_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    order = await _seed_order(db_session, client=buyer, order_number="NB-20260507-1001")
    res = await client.patch(
        f"/api/v1/orders/{order.id}/status",
        json={"status": "paid"},
        headers=auth_header(viewer_token),
    )
    assert res.status_code == 403


async def test_status_update_manager_allowed(
    client: AsyncClient,
    db_session: AsyncSession,
    manager_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    order = await _seed_order(db_session, client=buyer, order_number="NB-20260507-1001")
    res = await client.patch(
        f"/api/v1/orders/{order.id}/status",
        json={"status": "paid"},
        headers=auth_header(manager_token),
    )
    assert res.status_code == 200


async def test_list_viewer_can_read(
    client: AsyncClient, viewer_token: str, auth_header
) -> None:
    res = await client.get("/api/v1/orders", headers=auth_header(viewer_token))
    assert res.status_code == 200


# --- STATS -------------------------------------------------------------------


async def test_stats_endpoint(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    await _seed_order(
        db_session,
        client=buyer,
        order_number="NB-20260507-1001",
        final_total_usd=Decimal("100.00"),
        status=OrderStatus.COMPLETED,
    )
    await _seed_order(
        db_session,
        client=buyer,
        order_number="NB-20260507-1002",
        final_total_usd=Decimal("50.00"),
        status=OrderStatus.PENDING,
    )

    res = await client.get(
        "/api/v1/orders/stats", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total_orders"] == 2
    assert body["total_revenue_usd"] == 150.00
    assert body["avg_order_value_usd"] == 75.00
    statuses = {s["status"]: s["count"] for s in body["by_status"]}
    assert statuses.get("completed") == 1
    assert statuses.get("pending") == 1


# --- INTERNAL CREATE + ORDER NUMBER GENERATION -------------------------------


async def test_internal_create_happy_path(
    db_session: AsyncSession,
) -> None:
    payload = OrderInternalCreate(
        email="new-buyer@nano.io",
        discord="bb#9999",
        telegram=None,
        payment_method=PaymentMethod.PAYPAL,
        display_currency=DisplayCurrency.USD,
        discount_percent=0,
        comment="Test",
        items=[
            OrderItemCreate(
                service_snapshot={
                    "slug": "gta-cash-ps",
                    "title": "GTA Cash PS",
                },
                option_label="20 million",
                quantity=1,
                unit_price_usd=Decimal("19.99"),
                unit_price_eur=Decimal("16.99"),
            )
        ],
    )
    order = await OrderService(db_session).create_internal(payload)
    assert order.order_number.startswith("NB-")
    assert order.subtotal_usd == Decimal("19.99")
    assert order.final_total_usd == Decimal("19.99")
    assert len(order.items) == 1


async def test_internal_create_totals_with_discount(
    db_session: AsyncSession,
) -> None:
    payload = OrderInternalCreate(
        email="discount@nano.io",
        payment_method=PaymentMethod.USDT_TRC20,
        discount_percent=5,
        items=[
            OrderItemCreate(
                service_snapshot={
                    "slug": "gta-cash-ps",
                    "title": "GTA Cash PS",
                },
                quantity=2,
                unit_price_usd=Decimal("10.00"),
                unit_price_eur=Decimal("8.50"),
            )
        ],
    )
    order = await OrderService(db_session).create_internal(payload)
    # subtotal: 10 * 2 = 20.00
    # discount: 20 * 5% = 1.00
    # final: 20 - 1 = 19.00
    assert order.subtotal_usd == Decimal("20.00")
    assert order.discount_amount_usd == Decimal("1.00")
    assert order.final_total_usd == Decimal("19.00")


async def test_internal_create_reuses_existing_client(
    db_session: AsyncSession,
) -> None:
    existing = await _seed_client(db_session, email="repeat@nano.io")

    payload = OrderInternalCreate(
        email="repeat@nano.io",
        payment_method=PaymentMethod.PAYPAL,
        items=[
            OrderItemCreate(
                service_snapshot={"slug": "x", "title": "X"},
                quantity=1,
                unit_price_usd=Decimal("5.00"),
                unit_price_eur=Decimal("4.00"),
            )
        ],
    )
    order = await OrderService(db_session).create_internal(payload)
    assert order.client_id == existing.id


async def test_internal_create_creates_new_client(
    db_session: AsyncSession,
) -> None:
    payload = OrderInternalCreate(
        email="brand-new@nano.io",
        payment_method=PaymentMethod.PAYPAL,
        items=[
            OrderItemCreate(
                service_snapshot={"slug": "x", "title": "X"},
                quantity=1,
                unit_price_usd=Decimal("5.00"),
                unit_price_eur=Decimal("4.00"),
            )
        ],
    )
    order = await OrderService(db_session).create_internal(payload)
    assert order.client_id is not None


async def test_order_number_sequential_in_same_day(
    db_session: AsyncSession,
) -> None:
    payload = OrderInternalCreate(
        email="seq@nano.io",
        payment_method=PaymentMethod.PAYPAL,
        items=[
            OrderItemCreate(
                service_snapshot={"slug": "x", "title": "X"},
                quantity=1,
                unit_price_usd=Decimal("1.00"),
                unit_price_eur=Decimal("1.00"),
            )
        ],
    )
    o1 = await OrderService(db_session).create_internal(payload)
    o2 = await OrderService(db_session).create_internal(payload)
    o3 = await OrderService(db_session).create_internal(payload)

    parts1 = o1.order_number.split("-")
    parts2 = o2.order_number.split("-")
    parts3 = o3.order_number.split("-")
    seq1, seq2, seq3 = int(parts1[2]), int(parts2[2]), int(parts3[2])
    assert seq2 == seq1 + 1
    assert seq3 == seq2 + 1


async def test_order_number_format(
    db_session: AsyncSession,
) -> None:
    payload = OrderInternalCreate(
        email="fmt@nano.io",
        payment_method=PaymentMethod.PAYPAL,
        items=[
            OrderItemCreate(
                service_snapshot={"slug": "x", "title": "X"},
                quantity=1,
                unit_price_usd=Decimal("1.00"),
                unit_price_eur=Decimal("1.00"),
            )
        ],
    )
    order = await OrderService(db_session).create_internal(payload)

    import re

    assert re.match(r"^NB-\d{8}-\d{4}$", order.order_number)


# --- ENUM CONSTANTS REGRESSION (Manager-requested test) ----------------------


async def test_order_status_transitions_complete(db_session: AsyncSession) -> None:
    """Sanity check: every OrderStatus has a transitions entry."""
    del db_session
    for status in OrderStatus:
        assert status in ORDER_STATUS_TRANSITIONS, (
            f"Missing transitions for {status}"
        )
    assert ORDER_STATUS_TRANSITIONS[OrderStatus.CANCELLED] == frozenset()
    assert ORDER_STATUS_TRANSITIONS[OrderStatus.REFUNDED] == frozenset()


async def test_internal_create_freezes_service_snapshot(
    db_session: AsyncSession,
) -> None:
    """When `service_id` is supplied, the snapshot is built from the live row.

    Subsequent edits to the source service must NOT mutate the order's
    snapshot — that's the whole point of the immutable history.
    """
    from app.core.constants import Platform
    from app.features.games.models import Game
    from app.features.services.models import Service

    game = Game(slug="gta5", name="GTA 5 Online")
    db_session.add(game)
    await db_session.commit()
    await db_session.refresh(game)

    service = Service(
        game_id=game.id,
        slug="gta-cash-ps",
        title="GTA Cash Boost PS4/PS5",
        platform=Platform.PS,
        image_url="/uploads/services/x.webp",
        description=[],
        what_you_get=[],
        sections=[],
    )
    db_session.add(service)
    await db_session.commit()
    await db_session.refresh(service)

    payload = OrderInternalCreate(
        email="snap@nano.io",
        payment_method=PaymentMethod.PAYPAL,
        items=[
            OrderItemCreate(
                service_id=service.id,
                quantity=1,
                unit_price_usd=Decimal("19.99"),
                unit_price_eur=Decimal("16.99"),
            )
        ],
    )
    order = await OrderService(db_session).create_internal(payload)
    assert len(order.items) == 1
    snap = order.items[0].service_snapshot
    assert snap["slug"] == "gta-cash-ps"
    assert snap["title"] == "GTA Cash Boost PS4/PS5"
    assert snap["image_url"] == "/uploads/services/x.webp"
    assert snap["platform"] == "ps"
    assert snap["game_slug"] == "gta5"

    # Mutate the source service: order snapshot must remain frozen.
    service.title = "GTA Cash Boost PSN"
    await db_session.commit()

    refreshed = await OrderService(db_session).get(order.id)
    assert refreshed.items[0].service_snapshot["title"] == "GTA Cash Boost PS4/PS5"


async def test_internal_create_total_price_eur_computed(
    db_session: AsyncSession,
) -> None:
    payload = OrderInternalCreate(
        email="eur@nano.io",
        payment_method=PaymentMethod.PAYPAL,
        items=[
            OrderItemCreate(
                service_snapshot={"slug": "x", "title": "X"},
                quantity=3,
                unit_price_usd=Decimal("10.00"),
                unit_price_eur=Decimal("8.50"),
            )
        ],
    )
    order = await OrderService(db_session).create_internal(payload)
    assert order.items[0].total_price_usd == Decimal("30.00")
    assert order.items[0].total_price_eur == Decimal("25.50")


async def test_enum_values_match_db_pattern(db_session: AsyncSession) -> None:
    """Regression for the ENUM duplicate-create migration bug.

    The `name=` of each enum must match the migration so create_type=False
    behaves correctly. Asserts the python enums have exactly the values
    declared in 0004 migration.
    """
    del db_session
    assert {s.value for s in OrderStatus} == {
        "pending", "paid", "in_progress", "completed", "cancelled", "refunded",
    }
    assert {p.value for p in PaymentMethod} == {"paypal", "usdt_trc20"}
    assert {c.value for c in DisplayCurrency} == {"USD", "EUR"}
