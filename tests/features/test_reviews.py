from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Platform, UserRole
from app.core.security import create_access_token, hash_password
from app.features.games.models import Game
from app.features.reviews.models import Review
from app.features.services.models import Service
from app.features.users.models import User

pytestmark = pytest.mark.asyncio


async def _seed_service(db: AsyncSession, *, slug: str = "gta-cash-ps") -> Service:
    game = Game(slug=f"g-{slug}", name="Test Game")
    db.add(game)
    await db.commit()
    await db.refresh(game)

    service = Service(
        game_id=game.id,
        slug=slug,
        title="Test Service",
        platform=Platform.PS,
        description=[],
        what_you_get=[],
        sections=[],
    )
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return service


async def _seed_review(db: AsyncSession, **overrides) -> Review:
    defaults = {
        "author_name": "ShadowVortex",
        "service_id": None,
        "rating": 5,
        "text": "Fast delivery and everything exactly as described.",
        "is_featured": False,
        "sort_order": 0,
        "is_active": True,
        "is_deleted": False,
    }
    defaults.update(overrides)
    review = Review(**defaults)
    db.add(review)
    await db.commit()
    await db.refresh(review)
    return review


@pytest.fixture
async def manager_token(db_session: AsyncSession) -> str:
    user = User(
        email="manager-rev@nanoboost.io",
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
    res = await client.get("/api/v1/reviews", headers=auth_header(superadmin_token))
    assert res.status_code == 200
    assert res.json()["total"] == 0


async def test_list_paginated(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    for i in range(3):
        await _seed_review(db_session, author_name=f"User{i}", sort_order=i)

    res = await client.get(
        "/api/v1/reviews?page=1&page_size=2",
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


async def test_list_search(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    await _seed_review(
        db_session, author_name="Alice", text="Excellent fast delivery!"
    )
    await _seed_review(
        db_session, author_name="Bob", text="Got my modded account fine."
    )

    res = await client.get(
        "/api/v1/reviews?search=modded", headers=auth_header(superadmin_token)
    )
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["author_name"] == "Bob"


async def test_filter_by_service(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    s1 = await _seed_service(db_session, slug="svc-a")
    s2 = await _seed_service(db_session, slug="svc-b")
    await _seed_review(db_session, service_id=s1.id)
    await _seed_review(db_session, service_id=s2.id)

    res = await client.get(
        f"/api/v1/reviews?service_id={s1.id}",
        headers=auth_header(superadmin_token),
    )
    assert res.json()["total"] == 1


async def test_filter_by_featured(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    await _seed_review(db_session, author_name="Hot", is_featured=True)
    await _seed_review(db_session, author_name="Cold", is_featured=False)

    res = await client.get(
        "/api/v1/reviews?is_featured=true",
        headers=auth_header(superadmin_token),
    )
    assert res.json()["total"] == 1


# --- CREATE ------------------------------------------------------------------


def _create_payload(**overrides) -> dict:
    base = {
        "author_name": "New Author",
        "rating": 5,
        "text": "A solid ten-out-of-five experience overall.",
        "is_featured": False,
        "sort_order": 0,
        "is_active": True,
    }
    base.update(overrides)
    return base


async def test_create_as_manager(
    client: AsyncClient, manager_token: str, auth_header
) -> None:
    res = await client.post(
        "/api/v1/reviews",
        json=_create_payload(),
        headers=auth_header(manager_token),
    )
    assert res.status_code == 201
    assert res.json()["author_name"] == "New Author"


async def test_create_viewer_forbidden(
    client: AsyncClient, viewer_token: str, auth_header
) -> None:
    res = await client.post(
        "/api/v1/reviews",
        json=_create_payload(),
        headers=auth_header(viewer_token),
    )
    assert res.status_code == 403


async def test_create_invalid_rating(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.post(
        "/api/v1/reviews",
        json=_create_payload(rating=10),
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 422


async def test_create_text_too_short(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.post(
        "/api/v1/reviews",
        json=_create_payload(text="bad"),
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 422


async def test_create_with_service_link(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    service = await _seed_service(db_session)
    res = await client.post(
        "/api/v1/reviews",
        json=_create_payload(service_id=str(service.id)),
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["service_id"] == str(service.id)
    assert body["service"]["slug"] == service.slug
    assert body["service"]["title"] == service.title


async def test_create_with_nonexistent_service(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.post(
        "/api/v1/reviews",
        json=_create_payload(service_id=str(uuid4())),
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 404


# --- UPDATE / TOGGLE / DELETE -----------------------------------------------


async def test_update_partial(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    review = await _seed_review(db_session)
    res = await client.patch(
        f"/api/v1/reviews/{review.id}",
        json={"text": "Updated text body, longer than ten chars."},
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    assert res.json()["text"].startswith("Updated text")


async def test_toggle_active(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    review = await _seed_review(db_session, is_active=True)
    res = await client.patch(
        f"/api/v1/reviews/{review.id}/toggle",
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
    review = await _seed_review(db_session, is_featured=False)
    res = await client.patch(
        f"/api/v1/reviews/{review.id}/featured",
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
    review = await _seed_review(db_session)

    forbidden = await client.delete(
        f"/api/v1/reviews/{review.id}", headers=auth_header(manager_token)
    )
    assert forbidden.status_code == 403

    ok = await client.delete(
        f"/api/v1/reviews/{review.id}",
        headers=auth_header(superadmin_token),
    )
    assert ok.status_code == 204


async def test_reorder(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
    auth_header,
) -> None:
    r1 = await _seed_review(db_session, author_name="A", sort_order=0)
    r2 = await _seed_review(db_session, author_name="B", sort_order=1)

    res = await client.post(
        "/api/v1/reviews/reorder",
        json={
            "items": [
                {"id": str(r1.id), "sort_order": 5},
                {"id": str(r2.id), "sort_order": 0},
            ]
        },
        headers=auth_header(superadmin_token),
    )
    assert res.status_code == 200
    assert res.json()["updated"] == 2


# --- PUBLIC -----------------------------------------------------------------


async def test_public_list_returns_only_active(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_review(db_session, author_name="Visible", is_active=True)
    await _seed_review(db_session, author_name="Hidden", is_active=False)

    res = await client.get("/api/v1/public/reviews")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["author_name"] == "Visible"


async def test_public_featured_filter(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_review(db_session, author_name="Hot", is_featured=True)
    await _seed_review(db_session, author_name="Cold", is_featured=False)

    res = await client.get("/api/v1/public/reviews?featured=true")
    assert res.status_code == 200
    assert len(res.json()) == 1


async def test_public_filter_by_service(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    service = await _seed_service(db_session)
    await _seed_review(db_session, service_id=service.id, author_name="Linked")
    await _seed_review(db_session, service_id=None, author_name="Orphan")

    res = await client.get(f"/api/v1/public/reviews?service_id={service.id}")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["author_name"] == "Linked"


async def test_service_hard_delete_sets_review_service_id_null(
    db_session: AsyncSession,
) -> None:
    service = await _seed_service(db_session)
    review = await _seed_review(db_session, service_id=service.id)

    # Hard-delete the service to exercise the SET NULL FK behavior.
    await db_session.delete(service)
    await db_session.commit()

    rows = (
        await db_session.execute(
            select(Review.service_id).where(Review.id == review.id)
        )
    ).all()
    assert rows[0][0] is None
