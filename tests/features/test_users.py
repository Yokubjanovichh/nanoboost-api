import pytest
from httpx import AsyncClient

from app.core.constants import UserRole
from app.features.users.models import User

pytestmark = pytest.mark.asyncio


async def test_list_users_requires_auth(client: AsyncClient) -> None:
    res = await client.get("/api/v1/users")
    assert res.status_code == 401


async def test_list_users_forbidden_for_viewer(
    client: AsyncClient, viewer_token: str, auth_header
) -> None:
    res = await client.get("/api/v1/users", headers=auth_header(viewer_token))
    assert res.status_code == 403


async def test_list_users_as_superadmin(
    client: AsyncClient, superadmin_user: User, superadmin_token: str, auth_header
) -> None:
    res = await client.get("/api/v1/users", headers=auth_header(superadmin_token))
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 1
    assert body["page"] == 1
    assert any(u["email"] == superadmin_user.email for u in body["items"])


async def test_create_user_as_superadmin(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    payload = {
        "email": "new-admin@nanoboost.io",
        "password": "StrongPass123!",
        "full_name": "New Admin",
        "role": "admin",
    }
    res = await client.post(
        "/api/v1/users", json=payload, headers=auth_header(superadmin_token)
    )
    assert res.status_code == 201
    body = res.json()
    assert body["email"] == payload["email"]
    assert body["role"] == "admin"
    assert body["is_active"] is True


async def test_create_user_duplicate_email_conflict(
    client: AsyncClient,
    superadmin_user: User,
    superadmin_token: str,
    auth_header,
) -> None:
    res = await client.post(
        "/api/v1/users",
        json={
            "email": superadmin_user.email,
            "password": "AnotherPass123!",
            "role": "admin",
        },
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 409


async def test_create_user_as_viewer_forbidden(
    client: AsyncClient, viewer_token: str, auth_header
) -> None:
    res = await client.post(
        "/api/v1/users",
        json={"email": "x@nanoboost.io", "password": "Pass12345!", "role": "admin"},
        headers=auth_header(viewer_token),
    )
    assert res.status_code == 403


async def test_get_user(
    client: AsyncClient, superadmin_user: User, superadmin_token: str, auth_header
) -> None:
    res = await client.get(
        f"/api/v1/users/{superadmin_user.id}", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 200
    assert res.json()["email"] == superadmin_user.email


async def test_update_user(
    client: AsyncClient, superadmin_user: User, superadmin_token: str, auth_header
) -> None:
    res = await client.patch(
        f"/api/v1/users/{superadmin_user.id}",
        json={"full_name": "Renamed Admin", "role": "manager"},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["full_name"] == "Renamed Admin"
    assert body["role"] == UserRole.MANAGER.value


async def test_deactivate_user(
    client: AsyncClient, superadmin_user: User, superadmin_token: str, auth_header
) -> None:
    res = await client.delete(
        f"/api/v1/users/{superadmin_user.id}", headers=auth_header(superadmin_token)
    )
    assert res.status_code == 204

    follow_up = await client.get(
        f"/api/v1/users/{superadmin_user.id}", headers=auth_header(superadmin_token)
    )
    assert follow_up.status_code == 403  # InactiveUserError — user found but is_active=False
    assert follow_up.json()["detail"] == "User is inactive"
