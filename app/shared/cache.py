"""Redis-backed cache for /public/* endpoints.

Design choices:

- Silent degradation. If `REDIS_URL` is empty or Redis is unreachable,
  every helper returns the "no cache" answer and the caller proceeds
  with the live read. Endpoints add `X-Cache: BYPASS` so observability
  catches it. No throwing — the API stays up if Redis goes down.
- One global client, lazily built on first use. The connection pool is
  closed in the FastAPI lifespan.
- `delete_pattern` uses `SCAN`, never `KEYS`. `KEYS *` blocks Redis on
  large keyspaces and is banned in production guides.
- `cached_response` is the only thing endpoint handlers call. It owns
  the JSON encoding, the X-Cache header, and the cache state branching
  so handlers stay short.

Tests use fakeredis via `set_client_for_testing`, so the suite needs
no real Redis locally — only the CI job spins up redis:7-alpine for
end-to-end coverage.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as redis_async
import structlog
from fastapi import Response
from redis.exceptions import RedisError

from app.core.config import settings

logger = structlog.get_logger("nanoboost.cache")

_client: redis_async.Redis | None = None
_disabled: bool = False  # sticky: once we know the URL is empty, stop trying


async def get_client() -> redis_async.Redis | None:
    """Return the singleton Redis client, or None if the cache is off.

    Connection is built lazily so tests can swap settings before the
    first call. A failed PING during the first request flips `_disabled`
    so we don't pay the connect-timeout cost on every subsequent call.
    """
    global _client, _disabled
    if _disabled:
        return None
    if _client is not None:
        return _client
    if not settings.REDIS_URL:
        _disabled = True
        return None
    try:
        _client = redis_async.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        await _client.ping()
    except (RedisError, OSError) as exc:
        logger.warning("cache_unavailable", error=str(exc))
        _client = None
        _disabled = True
        return None
    return _client


def set_client_for_testing(client: redis_async.Redis | None) -> None:
    """Test hook: install a fakeredis (or None to force BYPASS).

    Passing `None` always disables the cache for the rest of the test —
    even when `REDIS_URL` is set (CI's real Redis service). Without this
    explicit disable, fixtures that intend "no cache" would silently
    connect to the live broker and serve stale data from prior tests.
    Use the `fakeredis_client` fixture when a test actually wants cache
    behaviour.
    """
    global _client, _disabled
    _client = client
    _disabled = client is None


async def close_client() -> None:
    """Called from FastAPI lifespan shutdown."""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        finally:
            _client = None


# --- Public helpers --------------------------------------------------------


async def cache_get(key: str) -> str | None:
    client = await get_client()
    if client is None:
        return None
    try:
        return await client.get(key)
    except RedisError as exc:
        logger.warning("cache_get_failed", key=key, error=str(exc))
        return None


async def cache_set(key: str, value: str, ttl: int) -> None:
    client = await get_client()
    if client is None:
        return
    try:
        await client.set(key, value, ex=ttl)
    except RedisError as exc:
        logger.warning("cache_set_failed", key=key, error=str(exc))


async def cache_delete_pattern(pattern: str) -> int:
    """SCAN + DEL — no blocking KEYS *. Returns the count of keys removed."""
    client = await get_client()
    if client is None:
        return 0
    deleted = 0
    try:
        async for key in client.scan_iter(match=pattern, count=200):
            await client.delete(key)
            deleted += 1
    except RedisError as exc:
        logger.warning("cache_delete_pattern_failed", pattern=pattern, error=str(exc))
    return deleted


async def cache_health() -> bool:
    client = await get_client()
    if client is None:
        return False
    try:
        return bool(await client.ping())
    except RedisError:
        return False


async def cache_status() -> str:
    """Human-readable status for /health.

    `disabled` means no `REDIS_URL` is configured and no test client has
    been injected. `ok` / `down` are the live broker states. Tests that
    swap in fakeredis via `set_client_for_testing` skip the URL check.
    """
    if not settings.REDIS_URL and _client is None:
        return "disabled"
    return "ok" if await cache_health() else "down"


# --- Endpoint helper -------------------------------------------------------


async def cached_response(
    *,
    key: str,
    ttl: int,
    build: Callable[[], Awaitable[Any]],
) -> Response:
    """Cache-aware JSON response.

    `build` must return a JSON-serialisable payload (dict or list — both
    fine for FastAPI's docs since we declare `response_model` on the
    handler). On cache HIT the cached bytes are returned verbatim, so
    the response_model is documentation only on that path.
    """
    client = await get_client()
    if client is None:
        payload = await build()
        body = json.dumps(payload, default=str)
        return Response(
            content=body,
            media_type="application/json",
            headers={"X-Cache": "BYPASS"},
        )

    try:
        cached = await client.get(key)
    except RedisError as exc:
        logger.warning("cached_response_get_failed", key=key, error=str(exc))
        cached = None

    if cached is not None:
        return Response(
            content=cached,
            media_type="application/json",
            headers={"X-Cache": "HIT"},
        )

    payload = await build()
    body = json.dumps(payload, default=str)
    try:
        await client.set(key, body, ex=ttl)
    except RedisError as exc:
        logger.warning("cached_response_set_failed", key=key, error=str(exc))
    return Response(
        content=body,
        media_type="application/json",
        headers={"X-Cache": "MISS"},
    )


# --- Domain invalidation ---------------------------------------------------

# Single source of truth for "which keys does a domain write blow up?".
# Service writes also clear the games cache because PublicGameRead carries
# service_count — a new active service changes a game row's payload.
_INVALIDATION_MAP: dict[str, tuple[str, ...]] = {
    "games": ("public:games:*",),
    "services": ("public:services:*", "public:games:*"),
    "reviews": ("public:reviews:*",),
}


async def invalidate_public_cache(entity: str) -> int:
    """Called from admin service-layer methods after a successful write.

    Idempotent and silent — a Redis outage during invalidation logs and
    moves on. Cached entries fall back to the per-key TTL.
    """
    patterns = _INVALIDATION_MAP.get(entity)
    if not patterns:
        logger.warning("cache_invalidate_unknown_entity", entity=entity)
        return 0
    total = 0
    for pattern in patterns:
        total += await cache_delete_pattern(pattern)
    return total
