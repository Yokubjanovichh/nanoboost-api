from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Platform, UserRole
from app.core.security import create_access_token, hash_password
from app.features.games.models import Game
from app.features.services.models import Service, ServiceOption
from app.features.users.models import User

pytestmark = pytest.mark.asyncio


async def _seed_game(db: AsyncSession, **overrides) -> Game:
    defaults = {
        "slug": "gta5",
        "name": "GTA 5 Online",
        "description": None,
        "image_url": None,
        "sort_order": 0,
        "is_active": True,
        "is_deleted": False,
    }
    defaults.update(overrides)
    game = Game(**defaults)
    db.add(game)
    await db.commit()
    await db.refresh(game)
    return game


async def _seed_service(db: AsyncSession, *, game: Game, **overrides) -> Service:
    defaults = {
        "game_id": game.id,
        "slug": "gta-cash-ps",
        "title": "GTA Online Cash Boost PS4/PS5",
        "platform": Platform.PS,
        "image_url": "/uploads/services/x.webp",
        "image_alt": None,
        "description": ["Paragraph 1"],
        "what_you_get": [],
        "sections": [],
        "seo_title": None,
        "seo_description": None,
        "is_featured": False,
        "sort_order": 0,
        "is_active": True,
        "is_deleted": False,
    }
    defaults.update(overrides)
    service = Service(**defaults)
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return service


@pytest.fixture
async def manager_token(db_session: AsyncSession) -> str:
    user = User(
        email="manager-svc@nanoboost.io",
        password_hash=hash_password("Pass12345!"),
        role=UserRole.MANAGER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return create_access_token(user.id, user.role)


@pytest.fixture
async def admin_token(db_session: AsyncSession) -> str:
    user = User(
        email="admin-svc@nanoboost.io",
        password_hash=hash_password("Pass12345!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return create_access_token(user.id, user.role)


# ---------- LIST -------------------------------------------------------------


async def test_list_empty(client: AsyncClient, superadmin_token: str, auth_header) -> None:
    res = await client.get("/api/v1/services", headers=auth_header(superadmin_token))
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 0
    assert body["items"] == []


async def test_list_paginated(
    client: AsyncClient, db_session: AsyncSession, superadmin_token: str, auth_header
) -> None:
    game = await _seed_game(db_session)
    for i in range(3):
        await _seed_service(db_session, game=game, slug=f"svc-{i}", sort_order=i)

    res = await client.get(
        "/api/v1/services?page=1&page_size=2",
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    # Frontend-required fields (Manager fix):
    first = body["items"][0]
    assert first["game"]["id"] == str(game.id)
    assert first["game"]["slug"] == "gta5"
    assert first["game"]["name"] == "GTA 5 Online"
    assert "default_option_price_usd" in first
    assert "default_option_price_eur" in first


async def test_list_includes_default_option_price(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    game = await _seed_game(db_session)
    service = await _seed_service(db_session, game=game, slug="cash")
    db_session.add(
        ServiceOption(
            service_id=service.id,
            label="20m",
            price_usd=Decimal("19.99"),
            price_eur=Decimal("16.99"),
            is_default=True,
            sort_order=0,
        )
    )
    db_session.add(
        ServiceOption(
            service_id=service.id,
            label="50m",
            price_usd=Decimal("29.99"),
            price_eur=Decimal("25.99"),
            is_default=False,
            sort_order=1,
        )
    )
    await db_session.commit()

    res = await client.get(
        "/api/v1/services", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 200
    item = res.json()["items"][0]
    assert item["options_count"] == 2
    assert item["default_option_price_usd"] == 19.99
    assert item["default_option_price_eur"] == 16.99


async def test_list_no_default_option_returns_null_prices(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    game = await _seed_game(db_session)
    service = await _seed_service(db_session, game=game, slug="no-default")
    # Add an option without is_default=True
    db_session.add(
        ServiceOption(
            service_id=service.id,
            label="50m",
            price_usd=Decimal("29.99"),
            price_eur=Decimal("25.99"),
            is_default=False,
            sort_order=0,
        )
    )
    await db_session.commit()

    res = await client.get(
        "/api/v1/services", headers=auth_header(superadmin_token)
    )
    item = res.json()["items"][0]
    assert item["options_count"] == 1
    assert item["default_option_price_usd"] is None
    assert item["default_option_price_eur"] is None


async def test_list_no_options_returns_null_prices(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    game = await _seed_game(db_session)
    await _seed_service(db_session, game=game, slug="empty-svc")

    res = await client.get(
        "/api/v1/services", headers=auth_header(superadmin_token)
    )
    item = res.json()["items"][0]
    assert item["options_count"] == 0
    assert item["default_option_price_usd"] is None
    assert item["default_option_price_eur"] is None


async def test_filter_by_game_id(
    client: AsyncClient, db_session: AsyncSession, superadmin_token: str, auth_header
) -> None:
    g1 = await _seed_game(db_session, slug="g1")
    g2 = await _seed_game(db_session, slug="g2")
    await _seed_service(db_session, game=g1, slug="s-g1")
    await _seed_service(db_session, game=g2, slug="s-g2")

    res = await client.get(
        f"/api/v1/services?game_id={g1.id}", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["slug"] == "s-g1"


async def test_filter_by_platform(
    client: AsyncClient, db_session: AsyncSession, superadmin_token: str, auth_header
) -> None:
    game = await _seed_game(db_session)
    await _seed_service(db_session, game=game, slug="ps-svc", platform=Platform.PS)
    await _seed_service(db_session, game=game, slug="pc-svc", platform=Platform.PC)

    res = await client.get(
        "/api/v1/services?platform=pc", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["slug"] == "pc-svc"


async def test_filter_by_featured(
    client: AsyncClient, db_session: AsyncSession, superadmin_token: str, auth_header
) -> None:
    game = await _seed_game(db_session)
    await _seed_service(db_session, game=game, slug="hot", is_featured=True)
    await _seed_service(db_session, game=game, slug="cold", is_featured=False)

    res = await client.get(
        "/api/v1/services?is_featured=true", headers=auth_header(superadmin_token)
    )
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["slug"] == "hot"


async def test_search_by_title(
    client: AsyncClient, db_session: AsyncSession, superadmin_token: str, auth_header
) -> None:
    game = await _seed_game(db_session)
    await _seed_service(db_session, game=game, slug="cash-ps", title="GTA Cash Boost PS")
    await _seed_service(db_session, game=game, slug="level-ps", title="GTA Level Boost PS")

    res = await client.get(
        "/api/v1/services?search=level", headers=auth_header(superadmin_token)
    )
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["slug"] == "level-ps"


# ---------- CREATE -----------------------------------------------------------


def _build_create_payload(game_id, **overrides) -> dict:
    base = {
        "game_id": str(game_id),
        "slug": "gta-cash-ps",
        "title": "GTA Online Cash Boost PS4/PS5",
        "platform": "ps",
        "image_url": "/uploads/services/x.webp",
        "image_alt": "alt",
        "description": ["Para 1", "Para 2"],
        "what_you_get": [
            {
                "title": "Cash Upgrade",
                "lead": "Use it for:",
                "items": ["Buy cars", "Buy weapons"],
            }
        ],
        "sections": [{"title": "About PS", "texts": ["Built for PS4/PS5."]}],
        "seo_title": "GTA Cash PS",
        "seo_description": "Buy cash for PS",
        "is_featured": True,
        "sort_order": 1,
        "is_active": True,
        "options": [
            {
                "label": "20 million",
                "price_usd": "19.99",
                "price_eur": "16.99",
                "is_default": True,
                "sort_order": 0,
            },
            {
                "label": "50 million",
                "price_usd": "29.99",
                "price_eur": "25.99",
                "is_default": False,
                "sort_order": 1,
            },
        ],
    }
    base.update(overrides)
    return base


async def test_create_as_manager(
    client: AsyncClient,
    db_session: AsyncSession,
    manager_token: str,
    auth_header,
) -> None:
    game = await _seed_game(db_session)
    res = await client.post(
        "/api/v1/services",
        json=_build_create_payload(game.id),
        headers=auth_header(manager_token),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["slug"] == "gta-cash-ps"
    assert len(body["options"]) == 2
    assert body["options_count"] == 2
    assert body["game"]["id"] == str(game.id)


async def test_create_as_admin(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_token: str,
    auth_header,
) -> None:
    game = await _seed_game(db_session)
    res = await client.post(
        "/api/v1/services",
        json=_build_create_payload(game.id, slug="gta-x", options=[]),
        headers=auth_header(admin_token),
    )
    assert res.status_code == 201


async def test_create_viewer_forbidden(
    client: AsyncClient,
    db_session: AsyncSession,
    viewer_token: str,
    auth_header,
) -> None:
    game = await _seed_game(db_session)
    res = await client.post(
        "/api/v1/services",
        json=_build_create_payload(game.id),
        headers=auth_header(viewer_token),
    )
    assert res.status_code == 403


async def test_create_non_existent_game(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.post(
        "/api/v1/services",
        json=_build_create_payload(uuid4()),
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 404


async def test_create_duplicate_slug(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    game = await _seed_game(db_session)
    await _seed_service(db_session, game=game, slug="gta-cash-ps")
    res = await client.post(
        "/api/v1/services",
        json=_build_create_payload(game.id),
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 409


async def test_create_multiple_defaults_invalid(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    game = await _seed_game(db_session)
    payload = _build_create_payload(game.id)
    payload["options"][1]["is_default"] = True  # 2 defaults
    res = await client.post(
        "/api/v1/services", json=payload, headers=auth_header(superadmin_token)
    )
    assert res.status_code == 422


async def test_create_empty_options(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    game = await _seed_game(db_session)
    res = await client.post(
        "/api/v1/services",
        json=_build_create_payload(game.id, options=[]),
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 201
    assert res.json()["options"] == []
    assert res.json()["options_count"] == 0


# ---------- GET / UPDATE / TOGGLE / DELETE -----------------------------------


async def test_get_with_options(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    game = await _seed_game(db_session)
    service = await _seed_service(db_session, game=game)
    db_session.add(
        ServiceOption(
            service_id=service.id,
            label="opt-1",
            price_usd=Decimal("9.99"),
            price_eur=Decimal("8.99"),
            is_default=True,
            sort_order=0,
        )
    )
    await db_session.commit()

    res = await client.get(
        f"/api/v1/services/{service.id}", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["options_count"] == 1
    assert body["options"][0]["label"] == "opt-1"
    assert body["options"][0]["price_usd"] == 9.99


async def test_update_partial(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    game = await _seed_game(db_session)
    service = await _seed_service(db_session, game=game)
    res = await client.patch(
        f"/api/v1/services/{service.id}",
        json={"title": "Renamed Service"},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    assert res.json()["title"] == "Renamed Service"


async def test_toggle_active(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    game = await _seed_game(db_session)
    service = await _seed_service(db_session, game=game, is_active=True)
    res = await client.patch(
        f"/api/v1/services/{service.id}/toggle",
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    assert res.json()["is_active"] is False


async def test_toggle_featured(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    game = await _seed_game(db_session)
    service = await _seed_service(db_session, game=game, is_featured=False)
    res = await client.patch(
        f"/api/v1/services/{service.id}/featured",
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    assert res.json()["is_featured"] is True


async def test_soft_delete_admin_only(
    client: AsyncClient,
    db_session: AsyncSession,
    manager_token: str,
    superadmin_token: str,
    auth_header,
) -> None:
    game = await _seed_game(db_session)
    service = await _seed_service(db_session, game=game)

    forbidden = await client.delete(
        f"/api/v1/services/{service.id}", headers=auth_header(manager_token)
    )
    assert forbidden.status_code == 403

    ok = await client.delete(
        f"/api/v1/services/{service.id}", headers=auth_header(superadmin_token)
    )
    assert ok.status_code == 204


async def test_reorder_atomic(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    game = await _seed_game(db_session)
    s1 = await _seed_service(db_session, game=game, slug="s1", sort_order=0)
    s2 = await _seed_service(db_session, game=game, slug="s2", sort_order=1)

    res = await client.post(
        "/api/v1/services/reorder",
        json={
            "items": [
                {"id": str(s1.id), "sort_order": 9},
                {"id": str(s2.id), "sort_order": 1},
            ]
        },
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    assert res.json()["updated"] == 2


async def test_reorder_no_match_returns_404(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.post(
        "/api/v1/services/reorder",
        json={"items": [{"id": str(uuid4()), "sort_order": 0}]},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 404


# ---------- PUBLIC ENDPOINTS -------------------------------------------------


async def test_public_list_featured_filter(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    game = await _seed_game(db_session, slug="gta5")
    await _seed_service(db_session, game=game, slug="hot-svc", is_featured=True)
    await _seed_service(db_session, game=game, slug="cold-svc", is_featured=False)

    res = await client.get("/api/v1/public/services?featured=true")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["slug"] == "hot-svc"
    # Internal fields not exposed:
    assert "sort_order" not in body[0]
    assert "is_active" not in body[0]
    assert "is_deleted" not in body[0]


async def test_public_detail_by_slug(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    game = await _seed_game(db_session, slug="gta5", name="GTA 5 Online")
    service = await _seed_service(db_session, game=game, slug="gta-cash-ps")
    db_session.add(
        ServiceOption(
            service_id=service.id,
            label="20 million",
            price_usd=Decimal("19.99"),
            price_eur=Decimal("16.99"),
            is_default=True,
            sort_order=0,
        )
    )
    await db_session.commit()

    res = await client.get("/api/v1/public/services/gta-cash-ps")
    assert res.status_code == 200
    body = res.json()
    assert body["slug"] == "gta-cash-ps"
    assert body["game"]["slug"] == "gta5"
    assert body["game"]["name"] == "GTA 5 Online"
    assert len(body["options"]) == 1
    assert body["options"][0]["price_usd"] == 19.99


async def test_public_inactive_service_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    game = await _seed_game(db_session)
    await _seed_service(
        db_session, game=game, slug="hidden-svc", is_active=False
    )
    res = await client.get("/api/v1/public/services/hidden-svc")
    assert res.status_code == 404


async def test_public_filter_by_game_slug(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    g1 = await _seed_game(db_session, slug="gta5", name="GTA 5")
    g2 = await _seed_game(db_session, slug="wow", name="WoW")
    await _seed_service(db_session, game=g1, slug="gta-svc")
    await _seed_service(db_session, game=g2, slug="wow-svc")

    res = await client.get("/api/v1/public/services?game=gta5")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["slug"] == "gta-svc"
