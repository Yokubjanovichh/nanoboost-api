"""Admin service-option CRUD with per-option discount (migration 0015).

Covers:
  * POST creates an option with discount_percent OR discount_amount_*
  * PATCH updates / clears an existing discount
  * Schema validator rejects invalid combinations at 422
  * Read response surfaces discounted_price_usd / discounted_price_eur
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.constants import GameStatus, Platform
from app.features.games.models import Game
from app.features.services.models import Service


@pytest.fixture(name="game_id")
async def _game(db_session):
    game = Game(slug="g1", name="Game 1", sort_order=0, status=GameStatus.ACTIVE)
    db_session.add(game)
    await db_session.commit()
    await db_session.refresh(game)
    return game.id


@pytest.fixture(name="service_id")
async def _service(db_session, game_id):
    svc = Service(
        game_id=game_id,
        slug="svc-discount",
        title="Boost service",
        platform=Platform.PS,
        description=["x"],
        what_you_get=[],
        sections=[],
        is_active=True,
        is_deleted=False,
        sort_order=0,
    )
    db_session.add(svc)
    await db_session.commit()
    await db_session.refresh(svc)
    return svc.id


def _option_payload(**overrides):
    base = {
        "label": "Standard",
        "price_usd": 100.0,
        "price_eur": 90.0,
        "is_default": True,
        "sort_order": 0,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_create_option_with_percent_discount(
    client_with_db, manager_user, auth_headers, service_id
):
    res = await client_with_db.post(
        f"/api/v1/services/{service_id}/options",
        headers=auth_headers(manager_user),
        json=_option_payload(discount_percent=15),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["discount_percent"] == 15
    assert body["discount_amount_usd"] is None
    assert body["discount_amount_eur"] is None
    assert body["discounted_price_usd"] == 85.0
    assert body["discounted_price_eur"] == 76.5


@pytest.mark.asyncio
async def test_create_option_with_amount_discount(
    client_with_db, manager_user, auth_headers, service_id
):
    res = await client_with_db.post(
        f"/api/v1/services/{service_id}/options",
        headers=auth_headers(manager_user),
        json=_option_payload(discount_amount_usd=10, discount_amount_eur=9),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["discount_percent"] is None
    assert body["discount_amount_usd"] == 10.0
    assert body["discount_amount_eur"] == 9.0
    assert body["discounted_price_usd"] == 90.0
    assert body["discounted_price_eur"] == 81.0


@pytest.mark.asyncio
async def test_create_option_without_discount_returns_originals(
    client_with_db, manager_user, auth_headers, service_id
):
    res = await client_with_db.post(
        f"/api/v1/services/{service_id}/options",
        headers=auth_headers(manager_user),
        json=_option_payload(),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["discount_percent"] is None
    assert body["discounted_price_usd"] == 100.0
    assert body["discounted_price_eur"] == 90.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_payload,reason",
    [
        (
            {"discount_percent": 10, "discount_amount_usd": 5, "discount_amount_eur": 4},
            "percent and amount together",
        ),
        ({"discount_amount_usd": 5}, "amount_usd without amount_eur"),
        ({"discount_amount_eur": 5}, "amount_eur without amount_usd"),
        ({"discount_percent": 0}, "percent equal to lower bound"),
        ({"discount_percent": -0.001}, "percent fractionally negative"),
        ({"discount_percent": 100}, "percent equal to upper bound"),
        ({"discount_percent": 100.001}, "percent fractionally above bound"),
        ({"discount_percent": 101}, "percent above range"),
        ({"discount_amount_usd": 0, "discount_amount_eur": 0}, "amount must be >0"),
    ],
)
async def test_create_option_rejects_invalid_discount(
    client_with_db, manager_user, auth_headers, service_id, bad_payload, reason
):
    res = await client_with_db.post(
        f"/api/v1/services/{service_id}/options",
        headers=auth_headers(manager_user),
        json=_option_payload(**bad_payload),
    )
    assert res.status_code == 422, f"expected 422 for {reason}, got {res.status_code}: {res.text}"


@pytest.mark.asyncio
async def test_create_option_with_fractional_percent(
    client_with_db, manager_user, auth_headers, service_id
):
    """Migration 0016: NUMERIC(7,3) lets sub-percent campaigns through —
    e.g. 50.003%. Response echoes the exact value and prices through the
    helper without rounding before quantize."""
    res = await client_with_db.post(
        f"/api/v1/services/{service_id}/options",
        headers=auth_headers(manager_user),
        json=_option_payload(discount_percent=50.003),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["discount_percent"] == 50.003
    # 100 * (100 - 50.003) / 100 = 49.997 -> quantize -> 50.00 (banker's).
    assert body["discounted_price_usd"] == 50.0


@pytest.mark.asyncio
async def test_patch_option_to_fractional_percent(
    client_with_db, manager_user, auth_headers, service_id
):
    create = await client_with_db.post(
        f"/api/v1/services/{service_id}/options",
        headers=auth_headers(manager_user),
        json=_option_payload(discount_percent=10),
    )
    option_id = create.json()["id"]

    patch = await client_with_db.patch(
        f"/api/v1/services/{service_id}/options/{option_id}",
        headers=auth_headers(manager_user),
        json={"discount_percent": 12.5},
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["discount_percent"] == 12.5
    # 100 * (100 - 12.5) / 100 = 87.50
    assert body["discounted_price_usd"] == 87.5


@pytest.mark.asyncio
async def test_patch_clears_discount_with_explicit_nulls(
    client_with_db, manager_user, auth_headers, service_id
):
    """Operator removes a campaign — explicit nulls flip the option back
    to its original price."""
    create = await client_with_db.post(
        f"/api/v1/services/{service_id}/options",
        headers=auth_headers(manager_user),
        json=_option_payload(discount_percent=25),
    )
    option_id = create.json()["id"]

    patch = await client_with_db.patch(
        f"/api/v1/services/{service_id}/options/{option_id}",
        headers=auth_headers(manager_user),
        json={"discount_percent": None},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["discount_percent"] is None
    assert patch.json()["discounted_price_usd"] == 100.0


@pytest.mark.asyncio
async def test_patch_switch_from_percent_to_amount(
    client_with_db, manager_user, auth_headers, service_id
):
    """Operator switches discount mode — must explicitly null the old
    mode in the same payload (validator rejects mixed)."""
    create = await client_with_db.post(
        f"/api/v1/services/{service_id}/options",
        headers=auth_headers(manager_user),
        json=_option_payload(discount_percent=10),
    )
    option_id = create.json()["id"]

    patch = await client_with_db.patch(
        f"/api/v1/services/{service_id}/options/{option_id}",
        headers=auth_headers(manager_user),
        json={
            "discount_percent": None,
            "discount_amount_usd": 7,
            "discount_amount_eur": 6,
        },
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["discount_percent"] is None
    assert body["discount_amount_usd"] == 7.0
    assert body["discounted_price_usd"] == 93.0


@pytest.mark.asyncio
async def test_patch_rejects_invalid_merged_state(
    client_with_db, manager_user, auth_headers, service_id, db_session
):
    """An option with an active amount discount must reject a PATCH that
    sets percent without nulling the amounts — service-layer re-validation
    catches the merged inconsistency that single-payload validation can't
    see on its own."""
    from uuid import UUID

    from app.features.services.models import ServiceOption

    create = await client_with_db.post(
        f"/api/v1/services/{service_id}/options",
        headers=auth_headers(manager_user),
        json=_option_payload(discount_amount_usd=10, discount_amount_eur=9),
    )
    option_id = create.json()["id"]
    # Sanity: row in DB is what we expect.
    row = await db_session.get(ServiceOption, UUID(option_id))
    assert row.discount_amount_usd == Decimal("10.00")

    # Sending only percent — payload alone is valid, but merged state is bad.
    patch = await client_with_db.patch(
        f"/api/v1/services/{service_id}/options/{option_id}",
        headers=auth_headers(manager_user),
        json={"discount_percent": 20},
    )
    assert patch.status_code == 422, patch.text
