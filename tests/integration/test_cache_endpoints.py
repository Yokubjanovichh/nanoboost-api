"""End-to-end cache behaviour for /public/* endpoints.

These tests pin the X-Cache contract (HIT / MISS / BYPASS) and the
invalidation hooks on admin writes. fakeredis stands in for Redis so
the tests run anywhere.
"""

from __future__ import annotations

import pytest

# --- MISS -> HIT cycle -----------------------------------------------------


@pytest.mark.asyncio
async def test_games_first_call_miss_second_hit(client_with_db, sample_game, fakeredis_client):
    first = await client_with_db.get("/api/v1/public/games")
    assert first.status_code == 200
    assert first.headers["x-cache"] == "MISS"

    second = await client_with_db.get("/api/v1/public/games")
    assert second.status_code == 200
    assert second.headers["x-cache"] == "HIT"
    # Cached bytes should be the same payload.
    assert second.content == first.content


@pytest.mark.asyncio
async def test_services_first_miss_second_hit(client_with_db, sample_service, fakeredis_client):
    first = await client_with_db.get("/api/v1/public/services")
    assert first.headers["x-cache"] == "MISS"
    second = await client_with_db.get("/api/v1/public/services")
    assert second.headers["x-cache"] == "HIT"


@pytest.mark.asyncio
async def test_reviews_first_miss_second_hit(client_with_db, fakeredis_client):
    first = await client_with_db.get("/api/v1/public/reviews")
    assert first.headers["x-cache"] == "MISS"
    second = await client_with_db.get("/api/v1/public/reviews")
    assert second.headers["x-cache"] == "HIT"


# --- BYPASS when Redis is off ---------------------------------------------


@pytest.mark.asyncio
async def test_bypass_when_redis_disabled(client_with_db, sample_game):
    # Default conftest fixture sets the cache client to None — that's the
    # BYPASS path. Endpoint must still return 200 with valid data.
    response = await client_with_db.get("/api/v1/public/games")
    assert response.status_code == 200
    assert response.headers["x-cache"] == "BYPASS"
    body = response.json()
    assert any(g["slug"] == "gta5" for g in body)


# --- Invalidation on admin writes -----------------------------------------


@pytest.mark.asyncio
async def test_admin_game_update_invalidates_cache(
    client_with_db, sample_game, manager_user, auth_headers, fakeredis_client
):
    # Warm the cache.
    miss = await client_with_db.get("/api/v1/public/games")
    assert miss.headers["x-cache"] == "MISS"
    hit = await client_with_db.get("/api/v1/public/games")
    assert hit.headers["x-cache"] == "HIT"

    # Admin updates the game.
    patch = await client_with_db.patch(
        f"/api/v1/games/{sample_game.id}",
        headers=auth_headers(manager_user),
        json={"name": "GTA 5 — updated"},
    )
    assert patch.status_code == 200

    # Next public read must be a MISS — invalidation hook fired.
    after = await client_with_db.get("/api/v1/public/games")
    assert after.headers["x-cache"] == "MISS"
    assert any(g["name"] == "GTA 5 — updated" for g in after.json())


@pytest.mark.asyncio
async def test_service_create_invalidates_games_cache_too(
    client_with_db,
    sample_game,
    manager_user,
    auth_headers,
    fakeredis_client,
):
    """A new service changes the games' service_count, so creating a
    service must invalidate the games cache, not just services."""
    # Warm games cache.
    await client_with_db.get("/api/v1/public/games")
    hit = await client_with_db.get("/api/v1/public/games")
    assert hit.headers["x-cache"] == "HIT"

    # Admin creates a service.
    res = await client_with_db.post(
        "/api/v1/services",
        headers=auth_headers(manager_user),
        json={
            "game_id": str(sample_game.id),
            "slug": "new-svc",
            "title": "New service",
            "platform": "ps",
            "description": ["one"],
            "what_you_get": [{"title": "T", "lead": "L", "items": ["i"]}],
            "sections": [{"title": "S", "texts": ["t"]}],
            "is_featured": False,
            "is_active": True,
            "sort_order": 0,
            "options": [
                {
                    "label": "Standard",
                    "price_usd": 9.99,
                    "price_eur": 8.99,
                    "is_default": True,
                    "sort_order": 0,
                }
            ],
        },
    )
    assert res.status_code == 201

    # Games cache should also be MISS now.
    after = await client_with_db.get("/api/v1/public/games")
    assert after.headers["x-cache"] == "MISS"
    games = after.json()
    gta5 = next(g for g in games if g["slug"] == "gta5")
    assert gta5["service_count"] == 1


# --- /health surfaces Redis status -----------------------------------------


@pytest.mark.asyncio
async def test_health_reports_redis_ok_when_cache_up(client, fakeredis_client):
    response = await client.get("/health")
    assert response.json()["redis"] == "ok"


@pytest.mark.asyncio
async def test_health_reports_redis_disabled_when_no_url(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "REDIS_URL", "")
    response = await client.get("/health")
    assert response.json()["redis"] == "disabled"
