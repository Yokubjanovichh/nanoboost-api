from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DisplayCurrency, OrderStatus, PaymentMethod, UserRole
from app.core.security import create_access_token, hash_password
from app.features.clients.models import Client
from app.features.orders.models import Order
from app.features.users.models import User

pytestmark = pytest.mark.asyncio


async def _seed_client(db: AsyncSession, **overrides) -> Client:
    defaults = {
        "email": "buyer@nanoboost.io",
        "discord": "buyer#1",
        "telegram": None,
        "notes": None,
    }
    defaults.update(overrides)
    obj = Client(**defaults)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def _seed_order_for(
    db: AsyncSession, client: Client, *, total: str, order_number: str
) -> Order:
    order = Order(
        order_number=order_number,
        client_id=client.id,
        status=OrderStatus.COMPLETED,
        payment_method=PaymentMethod.PAYPAL,
        display_currency=DisplayCurrency.USD,
        subtotal_usd=Decimal(total),
        discount_amount_usd=Decimal("0"),
        discount_percent=0,
        final_total_usd=Decimal(total),
    )
    db.add(order)
    await db.commit()
    return order


@pytest.fixture
async def manager_token(db_session: AsyncSession) -> str:
    user = User(
        email="manager-clients@nanoboost.io",
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
    res = await client.get("/api/v1/clients", headers=auth_header(superadmin_token))
    assert res.status_code == 200
    assert res.json()["total"] == 0


async def test_list_paginated(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    for i in range(3):
        await _seed_client(db_session, email=f"u{i}@x.io")

    res = await client.get(
        "/api/v1/clients?page=1&page_size=2",
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    assert res.json()["total"] == 3
    assert len(res.json()["items"]) == 2


async def test_search_by_email(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    await _seed_client(db_session, email="alice@nano.io")
    await _seed_client(db_session, email="bob@nano.io")

    res = await client.get(
        "/api/v1/clients?search=alice", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 200
    assert res.json()["total"] == 1


# --- DETAIL WITH STATS -------------------------------------------------------


async def test_get_with_stats_no_orders(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    res = await client.get(
        f"/api/v1/clients/{buyer.id}", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == buyer.email
    assert body["stats"]["total_orders"] == 0
    assert body["stats"]["total_spent_usd"] == 0


async def test_get_with_stats_with_orders(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    await _seed_order_for(db_session, buyer, total="50.00", order_number="NB-20260507-1001")
    await _seed_order_for(db_session, buyer, total="75.00", order_number="NB-20260507-1002")

    res = await client.get(
        f"/api/v1/clients/{buyer.id}", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["stats"]["total_orders"] == 2
    assert body["stats"]["total_spent_usd"] == 125.00
    assert body["stats"]["first_order_at"] is not None
    assert body["stats"]["last_order_at"] is not None


async def test_get_not_found(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.get(
        f"/api/v1/clients/{uuid4()}", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 404


# --- ORDERS LIST FOR CLIENT --------------------------------------------------


async def test_list_client_orders(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    other = await _seed_client(db_session, email="other@nano.io")
    await _seed_order_for(db_session, buyer, total="10.00", order_number="NB-20260507-1001")
    await _seed_order_for(db_session, buyer, total="20.00", order_number="NB-20260507-1002")
    await _seed_order_for(db_session, other, total="30.00", order_number="NB-20260507-1003")

    res = await client.get(
        f"/api/v1/clients/{buyer.id}/orders",
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 2


# --- UPDATE ------------------------------------------------------------------


async def test_update_notes_manager_allowed(
    client: AsyncClient,
    db_session: AsyncSession,
    manager_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    res = await client.patch(
        f"/api/v1/clients/{buyer.id}",
        json={"notes": "VIP customer", "discord": "newhandle#1"},
        headers=auth_header(manager_token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["notes"] == "VIP customer"
    assert body["discord"] == "newhandle#1"


async def test_update_viewer_forbidden(
    client: AsyncClient,
    db_session: AsyncSession,
    viewer_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    res = await client.patch(
        f"/api/v1/clients/{buyer.id}",
        json={"notes": "..."},
        headers=auth_header(viewer_token),
    )
    assert res.status_code == 403


async def test_list_clients_viewer_can_read(
    client: AsyncClient, viewer_token: str, auth_header
) -> None:
    res = await client.get("/api/v1/clients", headers=auth_header(viewer_token))
    assert res.status_code == 200


async def test_whatsapp_field_present_in_response(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    res = await client.get(
        f"/api/v1/clients/{buyer.id}", headers=auth_header(superadmin_token)
    )
    body = res.json()
    assert "whatsapp" in body
    assert body["whatsapp"] is None


async def test_update_whatsapp(
    client: AsyncClient,
    db_session: AsyncSession,
    manager_token: str,
    auth_header,
) -> None:
    buyer = await _seed_client(db_session)
    res = await client.patch(
        f"/api/v1/clients/{buyer.id}",
        json={"whatsapp": "+380501234567"},
        headers=auth_header(manager_token),
    )
    assert res.status_code == 200
    assert res.json()["whatsapp"] == "+380501234567"
