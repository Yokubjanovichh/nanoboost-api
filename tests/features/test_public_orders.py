from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Platform
from app.features.clients.models import Client
from app.features.games.models import Game
from app.features.services.models import Service, ServiceOption

pytestmark = pytest.mark.asyncio


async def _seed_service_with_option(
    db: AsyncSession,
    *,
    slug: str = "gta-cash-ps",
    price_usd: Decimal = Decimal("19.99"),
    price_eur: Decimal = Decimal("16.99"),
    is_active: bool = True,
) -> tuple[Service, ServiceOption]:
    game = Game(slug=f"game-for-{slug}", name="GTA 5 Online")
    db.add(game)
    await db.commit()
    await db.refresh(game)

    service = Service(
        game_id=game.id,
        slug=slug,
        title=f"Service {slug}",
        platform=Platform.PS,
        image_url="/uploads/services/x.webp",
        description=[],
        what_you_get=[],
        sections=[],
        is_active=is_active,
    )
    db.add(service)
    await db.commit()
    await db.refresh(service)

    option = ServiceOption(
        service_id=service.id,
        label="20 million",
        price_usd=price_usd,
        price_eur=price_eur,
        is_default=True,
        sort_order=0,
    )
    db.add(option)
    await db.commit()
    await db.refresh(option)

    return service, option


def _payload(
    service_id, option_id, *, payment="paypal", currency="USD", quantity=1, email="buyer@nano.io"
) -> dict:
    return {
        "email": email,
        "discord": "buyer#1234",
        "payment_method": payment,
        "display_currency": currency,
        "items": [
            {
                "service_id": str(service_id),
                "option_id": str(option_id),
                "quantity": quantity,
            }
        ],
    }


async def test_create_simple_paypal_order(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    service, option = await _seed_service_with_option(db_session)
    res = await client.post(
        "/api/v1/public/orders",
        json=_payload(service.id, option.id),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["order_number"].startswith("NB-")
    assert body["status"] == "pending"
    assert body["final_total_usd"] == 19.99
    assert body["display_currency"] == "USD"


async def test_create_with_usdt_5pct_discount(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    service, option = await _seed_service_with_option(
        db_session, price_usd=Decimal("100.00"), price_eur=Decimal("85.00")
    )
    res = await client.post(
        "/api/v1/public/orders",
        json=_payload(service.id, option.id, payment="usdt_trc20"),
    )
    assert res.status_code == 201
    # 100 - 5% = 95
    assert res.json()["final_total_usd"] == 95.00


async def test_create_with_eur_display_currency(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    service, option = await _seed_service_with_option(db_session)
    res = await client.post(
        "/api/v1/public/orders",
        json=_payload(service.id, option.id, currency="EUR"),
    )
    assert res.status_code == 201
    assert res.json()["display_currency"] == "EUR"


async def test_create_multiple_items(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    s1, o1 = await _seed_service_with_option(
        db_session, slug="cash", price_usd=Decimal("10.00"), price_eur=Decimal("8.50")
    )
    s2, o2 = await _seed_service_with_option(
        db_session, slug="level", price_usd=Decimal("20.00"), price_eur=Decimal("17.00")
    )

    payload = {
        "email": "multi@nano.io",
        "payment_method": "paypal",
        "display_currency": "USD",
        "items": [
            {"service_id": str(s1.id), "option_id": str(o1.id), "quantity": 2},
            {"service_id": str(s2.id), "option_id": str(o2.id), "quantity": 1},
        ],
    }
    res = await client.post("/api/v1/public/orders", json=payload)
    assert res.status_code == 201
    # 10*2 + 20*1 = 40
    assert res.json()["final_total_usd"] == 40.00


async def test_create_nonexistent_service_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, option = await _seed_service_with_option(db_session)
    res = await client.post(
        "/api/v1/public/orders",
        json=_payload(uuid4(), option.id),
    )
    assert res.status_code == 422


async def test_create_inactive_service_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    service, option = await _seed_service_with_option(db_session, is_active=False)
    res = await client.post(
        "/api/v1/public/orders",
        json=_payload(service.id, option.id),
    )
    assert res.status_code == 422


async def test_create_option_not_belonging_to_service_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    s1, _ = await _seed_service_with_option(db_session, slug="a")
    _, o2 = await _seed_service_with_option(db_session, slug="b")
    res = await client.post(
        "/api/v1/public/orders",
        json=_payload(s1.id, o2.id),
    )
    assert res.status_code == 422


async def test_create_empty_items_422(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/public/orders",
        json={
            "email": "empty@nano.io",
            "payment_method": "paypal",
            "items": [],
        },
    )
    assert res.status_code == 422


async def test_create_invalid_email_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    service, option = await _seed_service_with_option(db_session)
    res = await client.post(
        "/api/v1/public/orders",
        json=_payload(service.id, option.id, email="not-an-email"),
    )
    assert res.status_code == 422


async def test_creates_new_client(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    service, option = await _seed_service_with_option(db_session)
    res = await client.post(
        "/api/v1/public/orders",
        json=_payload(service.id, option.id, email="brand-new@nano.io"),
    )
    assert res.status_code == 201

    rows = (
        await db_session.execute(
            select(Client).where(Client.email == "brand-new@nano.io")
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_existing_client_contacts_filled(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    existing = Client(email="repeat@nano.io")
    db_session.add(existing)
    await db_session.commit()
    await db_session.refresh(existing)
    eid = existing.id

    service, option = await _seed_service_with_option(db_session)
    res = await client.post(
        "/api/v1/public/orders",
        json={
            "email": "repeat@nano.io",
            "discord": "added#0001",
            "telegram": "@added",
            "whatsapp": "+380501234567",
            "payment_method": "paypal",
            "items": [
                {
                    "service_id": str(service.id),
                    "option_id": str(option.id),
                    "quantity": 1,
                }
            ],
        },
    )
    assert res.status_code == 201

    refreshed = (
        await db_session.execute(select(Client).where(Client.id == eid))
    ).scalar_one()
    assert refreshed.discord == "added#0001"
    assert refreshed.telegram == "@added"
    assert refreshed.whatsapp == "+380501234567"


async def test_order_number_sequential_three_orders(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    service, option = await _seed_service_with_option(db_session)
    payload = _payload(service.id, option.id)

    numbers = []
    for _ in range(3):
        res = await client.post("/api/v1/public/orders", json=payload)
        assert res.status_code == 201
        numbers.append(res.json()["order_number"])

    # Each number unique and monotonically increasing for the same day prefix.
    assert len(set(numbers)) == 3
    seqs = [int(n.split("-")[2]) for n in numbers]
    assert seqs[1] == seqs[0] + 1
    assert seqs[2] == seqs[1] + 1


async def test_create_triggers_notification(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """Public POST schedules notification dispatch via BackgroundTasks."""
    from unittest.mock import AsyncMock

    captured = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.shared.notifications.OrderNotifier.notify_new_order", captured
    )

    service, option = await _seed_service_with_option(db_session)
    res = await client.post(
        "/api/v1/public/orders",
        json=_payload(service.id, option.id, email="notif@nano.io"),
    )
    assert res.status_code == 201
    # FastAPI flushes BackgroundTasks after response — httpx ASGI captures both.
    assert captured.await_count == 1


async def test_order_persists_snapshot(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    service, option = await _seed_service_with_option(db_session, slug="snap-test")
    res = await client.post(
        "/api/v1/public/orders",
        json=_payload(service.id, option.id),
    )
    assert res.status_code == 201

    from app.features.orders.models import Order, OrderItem

    order = (
        await db_session.execute(
            select(Order).where(Order.order_number == res.json()["order_number"])
        )
    ).scalar_one()

    item = (
        await db_session.execute(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )
    ).scalar_one()

    assert item.option_id == option.id
    assert item.option_label == option.label
    assert item.service_snapshot["slug"] == service.slug
    assert item.service_snapshot["title"] == service.title
    assert item.service_snapshot["platform"] == "ps"
