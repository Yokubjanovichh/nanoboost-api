import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import UserRole
from app.core.security import hash_password
from app.features.users.models import User

pytestmark = pytest.mark.asyncio


async def test_health(client: AsyncClient) -> None:
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


async def test_login_success(client: AsyncClient, superadmin_user: User) -> None:
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": superadmin_user.email, "password": "RootPass123!"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] > 0
    assert body["user"]["email"] == superadmin_user.email
    assert body["user"]["role"] == UserRole.SUPERADMIN.value


async def test_login_wrong_password(client: AsyncClient, superadmin_user: User) -> None:
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": superadmin_user.email, "password": "wrong-password"},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid credentials"


async def test_login_unknown_user(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@nanoboost.io", "password": "whatever123"},
    )
    assert res.status_code == 401


async def test_login_inactive_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = User(
        email="inactive@nanoboost.io",
        password_hash=hash_password("Inactive123!"),
        role=UserRole.ADMIN,
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()

    res = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Inactive123!"},
    )
    assert res.status_code == 403
    assert res.json()["detail"] == "User is inactive"


async def test_me_endpoint(
    client: AsyncClient, superadmin_user: User, superadmin_token: str, auth_header
) -> None:
    res = await client.get("/api/v1/auth/me", headers=auth_header(superadmin_token))
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == superadmin_user.email
    assert body["role"] == UserRole.SUPERADMIN.value


async def test_me_without_token(client: AsyncClient) -> None:
    res = await client.get("/api/v1/auth/me")
    assert res.status_code == 401


async def test_me_with_invalid_token(client: AsyncClient, auth_header) -> None:
    res = await client.get("/api/v1/auth/me", headers=auth_header("bogus-token"))
    assert res.status_code == 401


async def test_refresh_flow(client: AsyncClient, superadmin_user: User) -> None:
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": superadmin_user.email, "password": "RootPass123!"},
    )
    refresh_token = login_res.json()["refresh_token"]

    res = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["access_token"]
    assert body["refresh_token"]


async def test_refresh_with_access_token_fails(
    client: AsyncClient, superadmin_token: str
) -> None:
    res = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": superadmin_token}
    )
    assert res.status_code == 401
