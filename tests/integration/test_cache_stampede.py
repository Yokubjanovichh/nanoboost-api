"""Stampede protection for /public/* cache lookups.

The cache module's `cache_get_or_compute` / `cached_response` use a
Redis lock so concurrent MISS-path requests don't all stampede the
DB. These tests pin that behaviour and the fallback paths that keep
the API up if the lock infrastructure itself misbehaves.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.shared import cache as cache_module

# --- Happy paths ----------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_compute_miss_then_hit(fakeredis_client):
    """MISS → compute once → cache → HIT on the second call."""
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return {"data": "ok"}

    first = await cache_module.cache_get_or_compute(
        key="stampede:test:single", compute=compute, ttl=60
    )
    assert first == {"data": "ok"}
    assert calls == 1

    second = await cache_module.cache_get_or_compute(
        key="stampede:test:single", compute=compute, ttl=60
    )
    assert second == {"data": "ok"}
    assert calls == 1, "second call must hit the cache, not recompute"


# --- Concurrent stampede — THE critical test ------------------------------


@pytest.mark.asyncio
async def test_concurrent_requests_only_one_computes(fakeredis_client):
    """Ten parallel MISSes must produce exactly one compute() call.

    This is the whole point of the lock — if the assertion shifts, the
    cache layer just lost stampede protection."""
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        # Simulate a slow DB query. Plenty of time for the other
        # coroutines to land on the lock.
        await asyncio.sleep(0.1)
        return {"games": ["gta5", "wow"]}

    results = await asyncio.gather(
        *[
            cache_module.cache_get_or_compute(
                key="stampede:test:concurrent",
                compute=compute,
                ttl=60,
            )
            for _ in range(10)
        ]
    )

    assert all(r == {"games": ["gta5", "wow"]} for r in results)
    assert calls == 1, f"expected exactly 1 compute call, got {calls}"


# --- Fallback paths -------------------------------------------------------


@pytest.mark.asyncio
async def test_lock_timeout_falls_back_to_compute(fakeredis_client):
    """A stuck lock (owner crashed mid-compute) must not deadlock other
    callers. They wait up to max_wait_ms, then compute themselves."""
    # Pin a lock with a foreign owner so cache_get_or_compute can't
    # acquire it. fakeredis returns str when decode_responses=True.
    await fakeredis_client.set("lock:stampede:test:stuck", "ghost-owner", ex=10)

    async def compute():
        return "fallback-value"

    start = time.perf_counter()
    result = await cache_module.cache_get_or_compute(
        key="stampede:test:stuck",
        compute=compute,
        ttl=60,
        max_wait_ms=150,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert result == "fallback-value"
    # ~max_wait_ms then fallback; allow a generous upper bound for CI.
    assert elapsed_ms < 1000, f"took {elapsed_ms:.0f}ms — fallback should be quick"


@pytest.mark.asyncio
async def test_redis_down_short_circuits_to_compute(monkeypatch):
    """No Redis client → every call goes straight to compute().

    The autouse `_fresh_cache` fixture already installs None; this test
    asserts the cache-disabled behaviour explicitly."""
    cache_module.set_client_for_testing(None)

    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return "no-cache"

    r1 = await cache_module.cache_get_or_compute(
        key="stampede:test:degraded", compute=compute, ttl=60
    )
    r2 = await cache_module.cache_get_or_compute(
        key="stampede:test:degraded", compute=compute, ttl=60
    )

    assert r1 == r2 == "no-cache"
    assert calls == 2, "Redis-down must compute on every call"


# --- Lock ownership -------------------------------------------------------


@pytest.mark.asyncio
async def test_lock_release_only_by_owner(fakeredis_client):
    """The Lua compare-and-delete must reject a release from a
    non-owner. Otherwise a slow request whose lock TTL'd out could
    delete the next request's lock when it finally tries to release."""
    await fakeredis_client.set("lock:stampede:test:owned", "alice", ex=10)

    # Bob shouldn't be able to delete Alice's lock.
    await cache_module._release_lock(fakeredis_client, "lock:stampede:test:owned", "bob")
    assert await fakeredis_client.get("lock:stampede:test:owned") == "alice"

    # Alice releases her own lock cleanly.
    await cache_module._release_lock(fakeredis_client, "lock:stampede:test:owned", "alice")
    assert await fakeredis_client.get("lock:stampede:test:owned") is None


# --- Endpoint-level: cached_response shares the same protection ----------


@pytest.mark.asyncio
async def test_cached_response_is_stampede_protected(
    client_with_db, sample_game, fakeredis_client, monkeypatch
):
    """End-to-end smoke: ten concurrent GET /public/games hit the
    endpoint while the cache is cold. Only one of them should reach
    the repository layer."""
    from app.features.games import service as game_service

    real_list = game_service.GameService.list_public
    calls = 0

    async def counting_list(self):
        nonlocal calls
        calls += 1
        # Tiny await so the other coroutines have a chance to land on
        # the lock before this one returns.
        await asyncio.sleep(0.05)
        return await real_list(self)

    monkeypatch.setattr(game_service.GameService, "list_public", counting_list)

    responses = await asyncio.gather(
        *[client_with_db.get("/api/v1/public/games") for _ in range(10)]
    )

    assert all(r.status_code == 200 for r in responses)
    # At least one MISS (the lock owner) plus the rest as HIT/MISS-on-timeout.
    # `calls == 1` is the strict invariant — the whole point of the lock.
    assert calls == 1, f"expected one DB-level call, got {calls}"
