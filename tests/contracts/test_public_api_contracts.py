"""Runtime contract snapshots for the /api/v1/public/* surface.

These tests pin the *shape* of every public response — key names and
types, never values. The OpenAPI snapshot (covered by the lint-job
schema guard) catches static-schema drift; these catch runtime drift
the schema can't see: `response_model_exclude`, computed fields, JSON
serialisation quirks, the gap between "Pydantic class says X" and
"the wire actually carries X".

To update intentionally:

    uv run pytest tests/contracts/ --snapshot-update
    git add tests/contracts/__snapshots__/

Manager reviews the snapshot diff in the same PR as the code change —
every contract change is explicit.

Note on endpoint coverage:
- `GET /api/v1/public/games/{slug}` is in the TZ but not yet on the
  router (the games surface is list-only). Once it lands, add a test
  alongside test_public_games_contract; the snapshot file is already
  the right place for it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.constants import Platform
from app.features.services.models import Service, ServiceOption
from tests.contracts.conftest import extract_shape

# --- Fixture data ---------------------------------------------------------


@pytest.fixture
async def contract_service(db_session, sample_game):
    """One service + one option — enough to exercise nested shapes
    without dragging in values the snapshot would be sensitive to.

    Returns (service, option) so order/contact tests can build POST
    bodies without tripping the relationship's `lazy=\"raise\"` guard.
    """
    svc = Service(
        game_id=sample_game.id,
        slug="gta-cash-cars-ps",
        title="GTA Cash + Cars (PS)",
        platform=Platform.PS,
        image_desktop_url="/uploads/services/x.webp",
        image_mobile_url="/uploads/services/x-m.webp",
        image_alt="hero",
        description=["Cash + cars in one package."],
        what_you_get=[{"title": "GTA Online Money", "lead": "Includes:", "items": ["Cash"]}],
        sections=[{"title": "Designed for PlayStation", "texts": ["Optimised."]}],
        seo_title="GTA Cash Boost",
        seo_description="Buy GTA cash.",
        is_featured=True,
        sort_order=0,
        is_active=True,
        is_deleted=False,
    )
    db_session.add(svc)
    await db_session.flush()
    option = ServiceOption(
        service_id=svc.id,
        label="20 million",
        price_usd=Decimal("15.99"),
        price_eur=Decimal("13.99"),
        is_default=True,
        sort_order=0,
    )
    db_session.add(option)
    await db_session.commit()
    return svc, option


# --- Contracts ------------------------------------------------------------


@pytest.mark.contract
@pytest.mark.asyncio
async def test_public_games_contract(client_with_db, sample_game, snapshot):
    res = await client_with_db.get("/api/v1/public/games")
    assert res.status_code == 200
    assert extract_shape(res.json()) == snapshot


@pytest.mark.contract
@pytest.mark.asyncio
async def test_public_services_contract(client_with_db, contract_service, snapshot):
    res = await client_with_db.get("/api/v1/public/services")
    assert res.status_code == 200
    assert extract_shape(res.json()) == snapshot


@pytest.mark.contract
@pytest.mark.asyncio
async def test_public_services_game_filter_contract(
    client_with_db, contract_service, sample_game, snapshot
):
    res = await client_with_db.get(f"/api/v1/public/services?game={sample_game.slug}")
    assert res.status_code == 200
    assert extract_shape(res.json()) == snapshot


@pytest.mark.contract
@pytest.mark.asyncio
async def test_public_services_platform_filter_contract(client_with_db, contract_service, snapshot):
    res = await client_with_db.get("/api/v1/public/services?platform=ps")
    assert res.status_code == 200
    assert extract_shape(res.json()) == snapshot


@pytest.mark.contract
@pytest.mark.asyncio
async def test_public_services_search_contract(client_with_db, contract_service, snapshot):
    res = await client_with_db.get("/api/v1/public/services?search=cash")
    assert res.status_code == 200
    assert extract_shape(res.json()) == snapshot


@pytest.mark.contract
@pytest.mark.asyncio
async def test_public_service_detail_contract(client_with_db, contract_service, snapshot):
    service, _option = contract_service
    res = await client_with_db.get(f"/api/v1/public/services/{service.slug}")
    assert res.status_code == 200
    assert extract_shape(res.json()) == snapshot


@pytest.mark.contract
@pytest.mark.asyncio
async def test_public_reviews_contract(client_with_db, db_session, snapshot):
    """Seed one review so the list shape lands on an actual element,
    not an empty array."""
    from app.features.reviews.models import Review

    db_session.add(
        Review(
            author_name="ShadowVortex",
            rating=5,
            text="Fast delivery and exactly as described.",
            is_featured=True,
            sort_order=0,
            is_active=True,
        )
    )
    await db_session.commit()
    res = await client_with_db.get("/api/v1/public/reviews")
    assert res.status_code == 200
    assert extract_shape(res.json()) == snapshot


@pytest.mark.contract
@pytest.mark.asyncio
async def test_public_contact_post_contract(client_with_db, snapshot):
    """POST /public/contact response shape. Rate limit is in-process
    via fakeredis-or-bypass; we don't need a fakeredis fixture for a
    single call."""
    res = await client_with_db.post(
        "/api/v1/public/contact",
        json={
            "preferred_contact": "discord",
            "handle": "shadow#1234",
            "email": "shadow@example.com",
            "message": "Hi, I'd like to ask about a custom GTA boost setup.",
        },
    )
    assert res.status_code == 200, res.text
    assert extract_shape(res.json()) == snapshot


@pytest.mark.contract
@pytest.mark.asyncio
async def test_public_order_post_contract(client_with_db, contract_service, snapshot):
    """Bonus: POST /public/orders response shape. USDT (wallet-only)
    payment method skips the hosted-checkout provider so the call is
    deterministic; `checkout_url` stays None."""
    service, option = contract_service
    res = await client_with_db.post(
        "/api/v1/public/orders",
        json={
            "email": "buyer@example.com",
            "telegram": "@buyer",
            "payment_method": "usdt_trc20",
            "display_currency": "USD",
            "items": [
                {
                    "service_slug": service.slug,
                    "option_id": str(option.id),
                    "qty": 1,
                }
            ],
        },
    )
    assert res.status_code == 201, res.text
    assert extract_shape(res.json()) == snapshot
