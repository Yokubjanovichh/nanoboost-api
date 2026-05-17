"""Public services endpoint — input validators + filtering.

Pins PR #12 (slug pattern, page_size cap, platform enum) and PR #12's
drive-by fix to the Game.is_active → Game.status join migration.
"""

from __future__ import annotations

import pytest

# --- Validation (no DB needed for 422s — the validator rejects pre-handler) -


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "game=invalid'characters",
        "game=gta5'%20OR%201=1--",
        "game=UPPER",
        "game=-leading",
        "game=trailing-",
        "page_size=99999",
        "page_size=0",
        "page=0",
        "page=99999",
        "platform=invalid",
    ],
)
async def test_invalid_query_returns_422(client, query):
    res = await client.get(f"/api/v1/public/services?{query}")
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_path_slug_rejected_when_uppercase(client):
    res = await client.get("/api/v1/public/services/Uppercase")
    assert res.status_code == 422


# --- Happy path -------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_active_services(client_with_db, sample_service):
    res = await client_with_db.get("/api/v1/public/services")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["slug"] == sample_service.slug


@pytest.mark.asyncio
async def test_filter_by_game(client_with_db, sample_service, sample_game):
    res = await client_with_db.get(f"/api/v1/public/services?game={sample_game.slug}")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1


@pytest.mark.asyncio
async def test_filter_by_platform(client_with_db, sample_service):
    res = await client_with_db.get("/api/v1/public/services?platform=ps")
    assert res.status_code == 200
    assert len(res.json()) == 1

    res2 = await client_with_db.get("/api/v1/public/services?platform=pc")
    assert res2.status_code == 200
    assert res2.json() == []


@pytest.mark.asyncio
async def test_get_by_slug(client_with_db, sample_service):
    res = await client_with_db.get(f"/api/v1/public/services/{sample_service.slug}")
    assert res.status_code == 200
    assert res.json()["slug"] == sample_service.slug


@pytest.mark.asyncio
async def test_get_by_slug_missing_returns_404(client_with_db):
    res = await client_with_db.get("/api/v1/public/services/does-not-exist")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_page_size_at_max_accepted(client_with_db):
    res = await client_with_db.get("/api/v1/public/services?page_size=100")
    assert res.status_code == 200
