"""Startup smoke tests — incident coverage.

Today's P0 (apscheduler ModuleNotFoundError on Railway) was triggered
by a missing dependency in uv.lock. The container crashed at import.
A single test that imports app.main would have failed CI before the
PR could merge — this file is that test, plus the natural follow-ups.

If these go red, do not merge.
"""

from __future__ import annotations

import pytest


def test_app_imports_without_error():
    """The single test that would have caught the apscheduler P0.

    Importing app.main triggers every transitive dependency import
    (scheduler -> apscheduler, etc.). A missing wheel fails right here.
    """
    from app.main import app

    assert app is not None
    assert app.title == "Nanoboost Admin API"


@pytest.mark.asyncio
async def test_health_returns_200(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # Cache health is informational — value depends on REDIS_URL.
    assert "redis" in body


@pytest.mark.asyncio
async def test_public_games_returns_200_empty_db(client):
    """End-to-end: HTTP → middleware → router → repo → empty DB → JSON.

    Empty schema is fine — we're verifying the full stack wires up,
    not the data shape. Returns an empty list when no games exist.
    """
    response = await client.get("/api/v1/public/games")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_openapi_schema_renders(client):
    """If route signatures or schemas are malformed, /openapi.json
    raises during generation. A green here means every router declared
    in main can be inspected."""
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    body = response.json()
    assert body["info"]["title"] == "Nanoboost Admin API"
    assert "/api/v1/public/games" in body["paths"]
