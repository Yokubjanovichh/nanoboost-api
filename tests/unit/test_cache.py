"""Unit tests for the cache module helpers.

Backed by fakeredis so no real broker is needed locally. The CI test
job adds a real redis:7-alpine service for the integration smoke."""

from __future__ import annotations

import pytest

from app.shared import cache as cache_module


@pytest.mark.asyncio
async def test_set_then_get_roundtrip(fakeredis_client):
    await cache_module.cache_set("k", "hello", ttl=60)
    assert await cache_module.cache_get("k") == "hello"


@pytest.mark.asyncio
async def test_get_missing_key_returns_none(fakeredis_client):
    assert await cache_module.cache_get("nope") is None


@pytest.mark.asyncio
async def test_delete_pattern_uses_scan_not_keys(fakeredis_client):
    """SCAN iteration is what we use in prod — make sure the helper
    actually deletes everything matching the pattern."""
    for slug in ("a", "b", "c"):
        await cache_module.cache_set(f"public:games:v1:{slug}", "x", ttl=60)
    await cache_module.cache_set("public:services:v1:foo", "y", ttl=60)

    deleted = await cache_module.cache_delete_pattern("public:games:*")
    assert deleted == 3
    assert await cache_module.cache_get("public:games:v1:a") is None
    # Services key was not in the pattern — still there.
    assert await cache_module.cache_get("public:services:v1:foo") == "y"


@pytest.mark.asyncio
async def test_health_reports_ok_when_redis_up(fakeredis_client):
    assert await cache_module.cache_health() is True
    assert await cache_module.cache_status() == "ok"


@pytest.mark.asyncio
async def test_status_disabled_when_no_url(monkeypatch):
    # No fakeredis_client → set_client_for_testing(None) from autouse fixture.
    from app.core.config import settings

    monkeypatch.setattr(settings, "REDIS_URL", "")
    assert await cache_module.cache_status() == "disabled"
    assert await cache_module.cache_health() is False


@pytest.mark.asyncio
async def test_invalidate_services_clears_games_too(fakeredis_client):
    """Service writes change the games payload (service_count), so the
    invalidation map MUST clear public:games:* as well."""
    await cache_module.cache_set("public:games:v1", "g", ttl=60)
    await cache_module.cache_set("public:services:v1:foo", "s", ttl=60)
    await cache_module.cache_set("public:reviews:v1", "r", ttl=60)

    cleared = await cache_module.invalidate_public_cache("services")
    assert cleared == 2  # games + services
    assert await cache_module.cache_get("public:games:v1") is None
    assert await cache_module.cache_get("public:services:v1:foo") is None
    # Reviews must NOT be affected by a service write.
    assert await cache_module.cache_get("public:reviews:v1") == "r"


@pytest.mark.asyncio
async def test_invalidate_games_does_not_touch_services(fakeredis_client):
    await cache_module.cache_set("public:games:v1", "g", ttl=60)
    await cache_module.cache_set("public:services:v1:foo", "s", ttl=60)

    cleared = await cache_module.invalidate_public_cache("games")
    assert cleared == 1
    assert await cache_module.cache_get("public:games:v1") is None
    assert await cache_module.cache_get("public:services:v1:foo") == "s"


@pytest.mark.asyncio
async def test_invalidate_unknown_entity_is_safe(fakeredis_client):
    # Defensive: a typo in a caller shouldn't crash.
    cleared = await cache_module.invalidate_public_cache("widgets")
    assert cleared == 0
