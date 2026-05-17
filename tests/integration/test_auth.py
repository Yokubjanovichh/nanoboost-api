"""Auth + RBAC integration coverage."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_login_happy_path(client_with_db, admin_user):
    res = await client_with_db.post(
        "/api/v1/auth/login",
        json={"email": admin_user.email, "password": "TestPass123!"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["access_token"]
    assert body["user"]["email"] == admin_user.email
    assert body["user"]["role"] == "admin"


@pytest.mark.asyncio
async def test_login_wrong_password(client_with_db, admin_user):
    res = await client_with_db.post(
        "/api/v1/auth/login",
        json={"email": admin_user.email, "password": "wrong-password"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email(client_with_db):
    res = await client_with_db.post(
        "/api/v1/auth/login",
        json={"email": "nobody@nowhere.io", "password": "anything-here"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_me_endpoint_returns_current_user(client_with_db, admin_user, auth_headers):
    res = await client_with_db.get("/api/v1/auth/me", headers=auth_headers(admin_user))
    assert res.status_code == 200
    assert res.json()["email"] == admin_user.email


@pytest.mark.asyncio
async def test_admin_endpoint_requires_token(client_with_db):
    # No Authorization header → 401, not 403.
    res = await client_with_db.get("/api/v1/games")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_viewer_can_read_games(client_with_db, viewer_user, auth_headers):
    res = await client_with_db.get("/api/v1/games", headers=auth_headers(viewer_user))
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_viewer_cannot_delete_game(client_with_db, viewer_user, sample_game, auth_headers):
    # DELETE /games/{id} requires admin_or_above; viewer should be 403.
    res = await client_with_db.delete(
        f"/api/v1/games/{sample_game.id}",
        headers=auth_headers(viewer_user),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_delete_game(client_with_db, admin_user, sample_game, auth_headers):
    res = await client_with_db.delete(
        f"/api/v1/games/{sample_game.id}",
        headers=auth_headers(admin_user),
    )
    assert res.status_code == 204
