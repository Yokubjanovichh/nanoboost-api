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

import asyncio
import json
import uuid
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

# Atomic compare-and-delete: only release the lock if we still own it.
# `redis-py` strings get auto-encoded; the comparison is exact-bytes so
# stale owners (TTL-expired then re-acquired by a fresh request) can't
# accidentally delete the new lock.
_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

# Stampede defaults. Lock TTL > the slowest compute() we expect; the
# poll window is short so an unblocked waiter returns quickly. Both
# tunable per-call.
_DEFAULT_LOCK_TTL_SECONDS = 5
_DEFAULT_MAX_WAIT_MS = 500
_POLL_INTERVAL_MS = 50


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


# --- Stampede-protected lookup --------------------------------------------


async def _release_lock(client: redis_async.Redis, lock_key: str, owner: str) -> None:
    """Delete-if-still-mine.

    Real Redis runs the Lua script atomically, so the read-then-del
    can't race against another acquirer of the same lock. Fakeredis
    (used in tests) doesn't speak EVAL — we fall back to a non-atomic
    GET + ownership check + DEL. The lock TTL bounds the race window:
    the worst case under the fallback is that we delete a lock another
    request acquired in the millisecond between GET and DEL, and that
    request's compute is then unprotected for the rest of its run —
    still correct, just unlucky on stampede protection.
    """
    try:
        await client.eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, owner)
        return
    except RedisError:
        # Either real Redis disconnected mid-call or fakeredis doesn't
        # implement EVAL — try the safer non-atomic path before giving up.
        pass

    try:
        current = await client.get(lock_key)
        if current == owner:
            await client.delete(lock_key)
    except RedisError as exc:
        logger.warning("cache_lock_release_failed", key=lock_key, error=str(exc))


async def _cached_string_with_lock(
    *,
    client: redis_async.Redis,
    key: str,
    ttl: int,
    build: Callable[[], Awaitable[Any]],
    lock_ttl: int = _DEFAULT_LOCK_TTL_SECONDS,
    max_wait_ms: int = _DEFAULT_MAX_WAIT_MS,
) -> tuple[str, str]:
    """Stampede-protected MISS path. Returns (json_body, x_cache_label).

    Three branches:
      1. Lock acquired → compute, store, MISS.
      2. Lock held by another request → poll the cache for up to
         max_wait_ms; if it appears, return as HIT (the other request
         did the work for us).
      3. Lock-wait timeout → fall through to compute() ourselves to
         avoid deadlock. Logged so the threshold can be tuned.
    """
    lock_key = f"lock:{key}"
    owner = uuid.uuid4().hex[:12]

    try:
        acquired = await client.set(lock_key, owner, nx=True, ex=lock_ttl)
    except RedisError as exc:
        logger.warning("cache_lock_set_failed", key=lock_key, error=str(exc))
        payload = await build()
        return json.dumps(payload, default=str), "BYPASS"

    if acquired:
        logger.debug("cache_lock_acquired", key=key, owner=owner)
        try:
            payload = await build()
            body = json.dumps(payload, default=str)
            try:
                await client.set(key, body, ex=ttl)
            except RedisError as exc:
                logger.warning("cache_set_failed", key=key, error=str(exc))
            return body, "MISS"
        finally:
            await _release_lock(client, lock_key, owner)

    # Lock held by someone else — poll for their result.
    waited_ms = 0
    while waited_ms < max_wait_ms:
        await asyncio.sleep(_POLL_INTERVAL_MS / 1000)
        waited_ms += _POLL_INTERVAL_MS
        try:
            cached = await client.get(key)
        except RedisError:
            break
        if cached is not None:
            logger.debug("cache_lock_wait_hit", key=key, waited_ms=waited_ms)
            return cached, "HIT"

    # The other request crashed, ran past `lock_ttl`, or its result is
    # taking longer than we're willing to wait. Compute ourselves and
    # store — first writer wins on the set.
    logger.warning("cache_lock_timeout_fallback", key=key, waited_ms=waited_ms)
    payload = await build()
    body = json.dumps(payload, default=str)
    try:
        await client.set(key, body, ex=ttl)
    except RedisError as exc:
        logger.warning("cache_set_failed", key=key, error=str(exc))
    return body, "MISS"


async def cache_get_or_compute(
    *,
    key: str,
    compute: Callable[[], Awaitable[Any]],
    ttl: int,
    lock_ttl: int = _DEFAULT_LOCK_TTL_SECONDS,
    max_wait_ms: int = _DEFAULT_MAX_WAIT_MS,
) -> Any:
    """Generic cache-aside with stampede protection.

    Callers get back a Python value (the same shape `compute` returns).
    Use this when the value flows through Python code; use
    `cached_response` for HTTP handlers that want the `X-Cache` header
    on the wire.

    Concurrent MISS-path callers block on a Redis lock so only one of
    them actually runs `compute`. Redis-down short-circuits to a direct
    `compute()` call — losing stampede protection is preferable to
    refusing legitimate traffic.
    """
    client = await get_client()
    if client is None:
        return await compute()

    try:
        cached = await client.get(key)
    except RedisError as exc:
        logger.warning("cache_get_failed", key=key, error=str(exc))
        return await compute()
    if cached is not None:
        # Stored as a JSON string by the writer; decode for the caller.
        try:
            return json.loads(cached)
        except (TypeError, json.JSONDecodeError):
            return cached

    body, _label = await _cached_string_with_lock(
        client=client,
        key=key,
        ttl=ttl,
        build=compute,
        lock_ttl=lock_ttl,
        max_wait_ms=max_wait_ms,
    )
    try:
        return json.loads(body)
    except (TypeError, json.JSONDecodeError):
        return body


# --- Endpoint helper -------------------------------------------------------


async def cached_response(
    *,
    key: str,
    ttl: int,
    build: Callable[[], Awaitable[Any]],
) -> Response:
    """Cache-aware JSON response with stampede protection.

    `build` must return a JSON-serialisable payload. On HIT the cached
    bytes are returned verbatim — no Pydantic re-validation on the hot
    path, and `response_model` on the handler stays as docs.

    Concurrent MISS calls share a Redis lock so only one of them hits
    the DB; the rest see the freshly-written value via a short poll
    (X-Cache: HIT). Redis-down degrades to a direct build and
    X-Cache: BYPASS — same posture as before the lock was introduced.
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

    body, label = await _cached_string_with_lock(
        client=client,
        key=key,
        ttl=ttl,
        build=build,
    )
    return Response(
        content=body,
        media_type="application/json",
        headers={"X-Cache": label},
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
