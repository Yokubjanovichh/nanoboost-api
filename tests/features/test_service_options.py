from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Platform
from app.features.games.models import Game
from app.features.services.models import Service, ServiceOption

pytestmark = pytest.mark.asyncio


async def _setup(db_session: AsyncSession) -> Service:
    game = Game(slug="gta5", name="GTA 5 Online")
    db_session.add(game)
    await db_session.commit()
    await db_session.refresh(game)

    service = Service(
        game_id=game.id,
        slug="gta-cash-ps",
        title="GTA Cash PS",
        platform=Platform.PS,
        description=[],
        what_you_get=[],
        sections=[],
    )
    db_session.add(service)
    await db_session.commit()
    await db_session.refresh(service)
    return service


def _opt_payload(**overrides) -> dict:
    base = {
        "label": "20 million",
        "price_usd": "19.99",
        "price_eur": "16.99",
        "is_default": False,
        "sort_order": 0,
    }
    base.update(overrides)
    return base


async def test_list_options(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    service = await _setup(db_session)
    db_session.add(
        ServiceOption(
            service_id=service.id,
            label="opt-1",
            price_usd=Decimal("9.99"),
            price_eur=Decimal("8.99"),
            sort_order=0,
        )
    )
    await db_session.commit()

    res = await client.get(
        f"/api/v1/services/{service.id}/options",
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["label"] == "opt-1"


async def test_create_option(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    service = await _setup(db_session)
    res = await client.post(
        f"/api/v1/services/{service.id}/options",
        json=_opt_payload(),
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["label"] == "20 million"
    assert body["service_id"] == str(service.id)


async def test_update_option(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    service = await _setup(db_session)
    option = ServiceOption(
        service_id=service.id,
        label="orig",
        price_usd=Decimal("1.00"),
        price_eur=Decimal("1.00"),
        sort_order=0,
    )
    db_session.add(option)
    await db_session.commit()
    await db_session.refresh(option)

    res = await client.patch(
        f"/api/v1/services/{service.id}/options/{option.id}",
        json={"label": "renamed", "price_usd": "5.00"},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    assert res.json()["label"] == "renamed"
    assert res.json()["price_usd"] == 5.00


async def test_delete_option(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    service = await _setup(db_session)
    option = ServiceOption(
        service_id=service.id,
        label="x",
        price_usd=Decimal("1.00"),
        price_eur=Decimal("1.00"),
        sort_order=0,
    )
    db_session.add(option)
    await db_session.commit()
    await db_session.refresh(option)

    res = await client.delete(
        f"/api/v1/services/{service.id}/options/{option.id}",
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 204


async def test_set_default_unsets_old(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    service = await _setup(db_session)
    old_default = ServiceOption(
        service_id=service.id,
        label="old",
        price_usd=Decimal("1.00"),
        price_eur=Decimal("1.00"),
        is_default=True,
        sort_order=0,
    )
    new_one = ServiceOption(
        service_id=service.id,
        label="new",
        price_usd=Decimal("2.00"),
        price_eur=Decimal("2.00"),
        is_default=False,
        sort_order=1,
    )
    db_session.add_all([old_default, new_one])
    await db_session.commit()
    await db_session.refresh(old_default)
    await db_session.refresh(new_one)
    old_id = old_default.id
    new_id = new_one.id

    res = await client.patch(
        f"/api/v1/services/{service.id}/options/{new_id}",
        json={"is_default": True},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    assert res.json()["is_default"] is True

    # Verify via direct SQL select (avoid ORM identity map / expire issues)
    from sqlalchemy import select as sa_select

    rows = (
        await db_session.execute(
            sa_select(ServiceOption.id, ServiceOption.is_default).where(
                ServiceOption.service_id == service.id
            )
        )
    ).all()
    flags = {row.id: row.is_default for row in rows}
    assert flags[old_id] is False
    assert flags[new_id] is True


async def test_reorder_options(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    service = await _setup(db_session)
    o1 = ServiceOption(
        service_id=service.id,
        label="o1",
        price_usd=Decimal("1.00"),
        price_eur=Decimal("1.00"),
        sort_order=0,
    )
    o2 = ServiceOption(
        service_id=service.id,
        label="o2",
        price_usd=Decimal("2.00"),
        price_eur=Decimal("2.00"),
        sort_order=1,
    )
    db_session.add_all([o1, o2])
    await db_session.commit()
    await db_session.refresh(o1)
    await db_session.refresh(o2)

    res = await client.post(
        f"/api/v1/services/{service.id}/options/reorder",
        json={
            "items": [
                {"id": str(o1.id), "sort_order": 5},
                {"id": str(o2.id), "sort_order": 0},
            ]
        },
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    assert res.json()["updated"] == 2


async def test_options_viewer_forbidden(
    client: AsyncClient,
    db_session: AsyncSession,
    viewer_token: str,
    auth_header,
) -> None:
    service = await _setup(db_session)
    res = await client.post(
        f"/api/v1/services/{service.id}/options",
        json=_opt_payload(),
        headers=auth_header(viewer_token),
    )
    assert res.status_code == 403


async def test_options_cascade_on_service_hard_delete(
    db_session: AsyncSession,
) -> None:
    service = await _setup(db_session)
    db_session.add(
        ServiceOption(
            service_id=service.id,
            label="will-cascade",
            price_usd=Decimal("1.00"),
            price_eur=Decimal("1.00"),
            sort_order=0,
        )
    )
    await db_session.commit()

    # Verify option exists
    pre = (
        await db_session.execute(
            select(ServiceOption).where(ServiceOption.service_id == service.id)
        )
    ).scalars().all()
    assert len(pre) == 1

    # Hard delete the service (DB-level FK CASCADE)
    await db_session.delete(service)
    await db_session.commit()

    post = (
        await db_session.execute(
            select(ServiceOption).where(ServiceOption.service_id == service.id)
        )
    ).scalars().all()
    assert post == []
