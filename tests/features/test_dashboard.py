from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DisplayCurrency, OrderStatus, PaymentMethod, Platform
from app.features.clients.models import Client
from app.features.games.models import Game
from app.features.orders.models import Order, OrderItem
from app.features.services.models import Service

pytestmark = pytest.mark.asyncio


async def _seed_client(db: AsyncSession, **overrides) -> Client:
    defaults = {"email": "buyer@nano.io"}
    defaults.update(overrides)
    obj = Client(**defaults)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def _seed_service(db: AsyncSession, *, slug: str = "svc") -> Service:
    game = Game(slug=f"game-{slug}", name="GTA 5 Online")
    db.add(game)
    await db.commit()
    await db.refresh(game)

    service = Service(
        game_id=game.id,
        slug=slug,
        title=f"Service {slug}",
        platform=Platform.PS,
        description=[],
        what_you_get=[],
        sections=[],
    )
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return service


async def _seed_order(
    db: AsyncSession,
    *,
    client: Client,
    order_number: str,
    final_total: Decimal = Decimal("19.99"),
    status: OrderStatus = OrderStatus.PENDING,
    payment_method: PaymentMethod = PaymentMethod.PAYPAL,
    service: Service | None = None,
    quantity: int = 1,
) -> Order:
    order = Order(
        order_number=order_number,
        client_id=client.id,
        status=status,
        payment_method=payment_method,
        display_currency=DisplayCurrency.USD,
        subtotal_usd=final_total,
        discount_amount_usd=Decimal("0"),
        discount_percent=0,
        final_total_usd=final_total,
    )
    snap = {"slug": "svc", "title": "Service"}
    if service is not None:
        snap = {"slug": service.slug, "title": service.title}
    order.items.append(
        OrderItem(
            service_id=service.id if service is not None else None,
            service_snapshot=snap,
            option_label="20m",
            quantity=quantity,
            unit_price_usd=final_total / quantity,
            unit_price_eur=final_total / quantity,
            total_price_usd=final_total,
            total_price_eur=final_total,
        )
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


# --- Overview ---------------------------------------------------------------


async def test_overview_default_period_is_month(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.get(
        "/api/v1/dashboard/overview", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["period"] == "month"
    assert body["total_orders"] == 0
    assert body["total_revenue_usd"] == 0


async def test_overview_today_period(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    await _seed_order(
        db_session,
        client=buyer,
        order_number="NB-20260509-1001",
        final_total=Decimal("100.00"),
    )

    res = await client.get(
        "/api/v1/dashboard/overview?period=today",
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["period"] == "today"
    assert body["total_orders"] == 1
    assert body["total_revenue_usd"] == 100.00


async def test_overview_by_status_breakdown(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    await _seed_order(
        db_session, client=buyer, order_number="NB-20260509-1001",
        status=OrderStatus.PAID,
    )
    await _seed_order(
        db_session, client=buyer, order_number="NB-20260509-1002",
        status=OrderStatus.COMPLETED,
    )
    await _seed_order(
        db_session, client=buyer, order_number="NB-20260509-1003",
        status=OrderStatus.COMPLETED,
    )

    res = await client.get(
        "/api/v1/dashboard/overview", headers=auth_header(superadmin_token)
    )
    body = res.json()
    assert body["by_status"]["paid"] == 1
    assert body["by_status"]["completed"] == 2


async def test_overview_by_payment_method(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    await _seed_order(
        db_session, client=buyer, order_number="NB-20260509-1001",
        payment_method=PaymentMethod.PAYPAL,
    )
    await _seed_order(
        db_session, client=buyer, order_number="NB-20260509-1002",
        payment_method=PaymentMethod.USDT_TRC20,
    )

    res = await client.get(
        "/api/v1/dashboard/overview", headers=auth_header(superadmin_token)
    )
    body = res.json()
    assert body["by_payment_method"]["paypal"] == 1
    assert body["by_payment_method"]["usdt_trc20"] == 1


async def test_overview_average_order_value(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    await _seed_order(
        db_session, client=buyer, order_number="NB-20260509-1001",
        final_total=Decimal("50.00"),
    )
    await _seed_order(
        db_session, client=buyer, order_number="NB-20260509-1002",
        final_total=Decimal("150.00"),
    )

    res = await client.get(
        "/api/v1/dashboard/overview", headers=auth_header(superadmin_token)
    )
    body = res.json()
    assert body["average_order_value_usd"] == 100.00


async def test_overview_new_clients_count(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    await _seed_client(db_session, email="a@x.io")
    await _seed_client(db_session, email="b@x.io")

    res = await client.get(
        "/api/v1/dashboard/overview", headers=auth_header(superadmin_token)
    )
    assert res.json()["new_clients"] == 2


async def test_overview_empty_period(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.get(
        "/api/v1/dashboard/overview?period=year",
        headers=auth_header(superadmin_token),
    )
    body = res.json()
    assert body["total_orders"] == 0
    assert body["total_revenue_usd"] == 0
    assert body["average_order_value_usd"] == 0
    assert body["new_clients"] == 0


async def test_overview_period_validation(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.get(
        "/api/v1/dashboard/overview?period=invalid",
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 422


# --- Revenue chart ----------------------------------------------------------


async def test_revenue_chart_empty_days_included(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    await _seed_order(
        db_session, client=buyer, order_number="NB-20260509-1001",
        final_total=Decimal("75.00"),
    )

    res = await client.get(
        "/api/v1/dashboard/revenue-chart?period=week",
        headers=auth_header(superadmin_token),
    )
    body = res.json()
    # 7 days plus today's start → at least 7 entries
    assert len(body["items"]) >= 7
    assert all("date" in item for item in body["items"])
    # At least one item has the seeded revenue
    revenues = [item["revenue_usd"] for item in body["items"]]
    assert 75.00 in revenues


async def test_revenue_chart_period_today(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.get(
        "/api/v1/dashboard/revenue-chart?period=today",
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    assert res.json()["period"] == "today"
    # Today is at least 1 entry (today itself)
    assert len(res.json()["items"]) >= 1


# --- Top services -----------------------------------------------------------


async def test_top_services_aggregation(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    s1 = await _seed_service(db_session, slug="hot")
    s2 = await _seed_service(db_session, slug="cold")
    await _seed_order(
        db_session, client=buyer, order_number="NB-20260509-1001",
        service=s1, final_total=Decimal("100.00"),
    )
    await _seed_order(
        db_session, client=buyer, order_number="NB-20260509-1002",
        service=s1, final_total=Decimal("50.00"),
    )
    await _seed_order(
        db_session, client=buyer, order_number="NB-20260509-1003",
        service=s2, final_total=Decimal("30.00"),
    )

    res = await client.get(
        "/api/v1/dashboard/top-services",
        headers=auth_header(superadmin_token),
    )
    body = res.json()
    assert len(body["items"]) == 2
    # Ordered by revenue desc
    assert body["items"][0]["slug"] == "hot"
    assert body["items"][0]["orders_count"] == 2
    assert body["items"][0]["revenue_usd"] == 150.00
    assert body["items"][1]["slug"] == "cold"


async def test_top_services_limit(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    services = []
    for i in range(5):
        services.append(await _seed_service(db_session, slug=f"s{i}"))
    for i, svc in enumerate(services):
        await _seed_order(
            db_session,
            client=buyer,
            order_number=f"NB-20260509-100{i + 1}",
            service=svc,
            final_total=Decimal("10.00"),
        )

    res = await client.get(
        "/api/v1/dashboard/top-services?limit=2",
        headers=auth_header(superadmin_token),
    )
    assert len(res.json()["items"]) == 2


# --- Recent orders ----------------------------------------------------------


async def test_recent_orders_with_client_embedded(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    await _seed_order(
        db_session, client=buyer, order_number="NB-20260509-1001"
    )

    res = await client.get(
        "/api/v1/dashboard/recent-orders?limit=5",
        headers=auth_header(superadmin_token),
    )
    body = res.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["client"]["email"] == buyer.email


async def test_recent_orders_limit_validation(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.get(
        "/api/v1/dashboard/recent-orders?limit=999",
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 422


# --- Permissions -------------------------------------------------------------


async def test_dashboard_viewer_can_read(
    client: AsyncClient, viewer_token: str, auth_header
) -> None:
    res = await client.get(
        "/api/v1/dashboard/overview", headers=auth_header(viewer_token)
    )
    assert res.status_code == 200


async def test_dashboard_unauthenticated_401(client: AsyncClient) -> None:
    res = await client.get("/api/v1/dashboard/overview")
    assert res.status_code == 401
