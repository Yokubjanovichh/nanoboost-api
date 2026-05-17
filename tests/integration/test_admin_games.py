"""Admin games CRUD + RBAC + the Game.status enum migration (PR #6)."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_create_game_as_manager(client_with_db, manager_user, auth_headers):
    res = await client_with_db.post(
        "/api/v1/games",
        headers=auth_headers(manager_user),
        json={
            "slug": "newgame",
            "name": "New Game",
            "description": "fresh",
            "status": "coming_soon",
            "sort_order": 5,
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["slug"] == "newgame"
    assert body["status"] == "coming_soon"
    assert body["sort_order"] == 5


@pytest.mark.asyncio
async def test_create_game_rejects_duplicate_slug(
    client_with_db, manager_user, sample_game, auth_headers
):
    res = await client_with_db.post(
        "/api/v1/games",
        headers=auth_headers(manager_user),
        json={
            "slug": sample_game.slug,
            "name": "Dup",
            "status": "active",
        },
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_create_game_rejects_bad_status(client_with_db, manager_user, auth_headers):
    res = await client_with_db.post(
        "/api/v1/games",
        headers=auth_headers(manager_user),
        json={
            "slug": "g",
            "name": "x",
            "status": "not_a_status",  # GameStatus enum rejects
        },
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_update_status_to_hidden(client_with_db, manager_user, sample_game, auth_headers):
    res = await client_with_db.patch(
        f"/api/v1/games/{sample_game.id}",
        headers=auth_headers(manager_user),
        json={"status": "hidden"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "hidden"


@pytest.mark.asyncio
async def test_delete_game_requires_admin(client_with_db, manager_user, sample_game, auth_headers):
    # Manager cannot delete — only admin_or_above.
    res = await client_with_db.delete(
        f"/api/v1/games/{sample_game.id}",
        headers=auth_headers(manager_user),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_toggle_endpoint_removed_in_phase5(
    client_with_db, manager_user, sample_game, auth_headers
):
    """PR #6 explicitly removed PATCH /games/{id}/toggle when is_active
    became a tri-state enum. This test pins the removal."""
    res = await client_with_db.patch(
        f"/api/v1/games/{sample_game.id}/toggle",
        headers=auth_headers(manager_user),
    )
    assert res.status_code in (404, 405)
