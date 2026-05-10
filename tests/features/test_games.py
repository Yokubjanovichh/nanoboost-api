import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.games.models import Game

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


async def test_list_empty(client: AsyncClient, superadmin_token: str, auth_header) -> None:
    res = await client.get("/api/v1/games", headers=auth_header(superadmin_token))
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 0
    assert body["items"] == []


async def test_list_paginated(
    client: AsyncClient, db_session: AsyncSession, superadmin_token: str, auth_header
) -> None:
    for i in range(3):
        await _seed_game(db_session, slug=f"game-{i}", name=f"Game {i}", sort_order=i)

    res = await client.get(
        "/api/v1/games?page=1&page_size=2", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["pages"] == 2
    assert len(body["items"]) == 2


async def test_list_filter_is_active(
    client: AsyncClient, db_session: AsyncSession, superadmin_token: str, auth_header
) -> None:
    await _seed_game(db_session, slug="active-game", is_active=True)
    await _seed_game(db_session, slug="inactive-game", is_active=False)

    res = await client.get(
        "/api/v1/games?is_active=false", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["slug"] == "inactive-game"


async def test_list_search(
    client: AsyncClient, db_session: AsyncSession, superadmin_token: str, auth_header
) -> None:
    await _seed_game(db_session, slug="gta5", name="GTA 5 Online")
    await _seed_game(db_session, slug="wow", name="World of Warcraft")

    res = await client.get(
        "/api/v1/games?search=warcraft", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["slug"] == "wow"


async def test_create_as_superadmin(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.post(
        "/api/v1/games",
        json={"slug": "gta5", "name": "GTA 5 Online", "sort_order": 1},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["slug"] == "gta5"
    assert body["is_active"] is True


async def test_create_as_manager_allowed(
    client: AsyncClient, db_session: AsyncSession, auth_header
) -> None:
    from app.core.constants import UserRole
    from app.core.security import create_access_token, hash_password
    from app.features.users.models import User

    manager = User(
        email="manager@nanoboost.io",
        password_hash=hash_password("Pass12345!"),
        role=UserRole.MANAGER,
        is_active=True,
    )
    db_session.add(manager)
    await db_session.commit()
    await db_session.refresh(manager)
    token = create_access_token(manager.id, manager.role)

    res = await client.post(
        "/api/v1/games",
        json={"slug": "wow", "name": "World of Warcraft"},
        headers=auth_header(token),
    )
    assert res.status_code == 201


async def test_create_as_viewer_forbidden(
    client: AsyncClient, viewer_token: str, auth_header
) -> None:
    res = await client.post(
        "/api/v1/games",
        json={"slug": "gta5", "name": "GTA 5 Online"},
        headers=auth_header(viewer_token),
    )
    assert res.status_code == 403


async def test_create_duplicate_slug_conflict(
    client: AsyncClient, db_session: AsyncSession, superadmin_token: str, auth_header
) -> None:
    await _seed_game(db_session, slug="gta5")
    res = await client.post(
        "/api/v1/games",
        json={"slug": "gta5", "name": "Another GTA"},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 409


async def test_create_invalid_slug_validation(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.post(
        "/api/v1/games",
        json={"slug": "Has Spaces", "name": "Bad Slug"},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 422


async def test_get_game_found(
    client: AsyncClient, db_session: AsyncSession, superadmin_token: str, auth_header
) -> None:
    game = await _seed_game(db_session)
    res = await client.get(
        f"/api/v1/games/{game.id}", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 200
    assert res.json()["slug"] == "gta5"


async def test_get_game_not_found(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.get(
        "/api/v1/games/00000000-0000-0000-0000-000000000000",
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 404


async def test_update_partial(
    client: AsyncClient, db_session: AsyncSession, superadmin_token: str, auth_header
) -> None:
    game = await _seed_game(db_session)
    res = await client.patch(
        f"/api/v1/games/{game.id}",
        json={"name": "GTA Online Renamed"},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "GTA Online Renamed"
    assert body["slug"] == "gta5"


async def test_toggle_active(
    client: AsyncClient, db_session: AsyncSession, superadmin_token: str, auth_header
) -> None:
    game = await _seed_game(db_session, is_active=True)
    res = await client.patch(
        f"/api/v1/games/{game.id}/toggle", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 200
    assert res.json()["is_active"] is False


async def test_soft_delete_admin_only(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_header,
    superadmin_token: str,
) -> None:
    from app.core.constants import UserRole
    from app.core.security import create_access_token, hash_password
    from app.features.users.models import User

    manager = User(
        email="mgr@nanoboost.io",
        password_hash=hash_password("Pass12345!"),
        role=UserRole.MANAGER,
        is_active=True,
    )
    db_session.add(manager)
    await db_session.commit()
    await db_session.refresh(manager)
    manager_token = create_access_token(manager.id, manager.role)

    game = await _seed_game(db_session)

    forbidden = await client.delete(
        f"/api/v1/games/{game.id}", headers=auth_header(manager_token)
    )
    assert forbidden.status_code == 403

    ok = await client.delete(
        f"/api/v1/games/{game.id}", headers=auth_header(superadmin_token)
    )
    assert ok.status_code == 204

    follow_up = await client.get(
        f"/api/v1/games/{game.id}", headers=auth_header(superadmin_token)
    )
    assert follow_up.status_code == 404


async def test_reorder_bulk(
    client: AsyncClient, db_session: AsyncSession, superadmin_token: str, auth_header
) -> None:
    g1 = await _seed_game(db_session, slug="g1", sort_order=0)
    g2 = await _seed_game(db_session, slug="g2", sort_order=1)

    res = await client.post(
        "/api/v1/games/reorder",
        json={
            "items": [
                {"id": str(g1.id), "sort_order": 5},
                {"id": str(g2.id), "sort_order": 3},
            ]
        },
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    assert res.json()["updated"] == 2

    listing = await client.get(
        "/api/v1/games?sort=sort_order", headers=auth_header(superadmin_token)
    )
    items = listing.json()["items"]
    assert items[0]["slug"] == "g2"
    assert items[1]["slug"] == "g1"


async def test_public_endpoint_only_active(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_game(db_session, slug="public-active", is_active=True, sort_order=1)
    await _seed_game(db_session, slug="public-inactive", is_active=False, sort_order=2)

    res = await client.get("/api/v1/public/games")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["slug"] == "public-active"
    assert "sort_order" not in body[0]
    assert "is_active" not in body[0]


async def test_public_endpoint_no_auth_required(client: AsyncClient) -> None:
    res = await client.get("/api/v1/public/games")
    assert res.status_code == 200
