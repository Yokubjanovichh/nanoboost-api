"""Redis-backed per-key request counter.

Used for the public contact endpoint and reusable for any future
public write that needs spam protection. Falls back to allow-all when
Redis is unavailable so the API stays up if the broker is down — same
posture as the cache module.
"""

from __future__ import annotations

import structlog
from redis.exceptions import RedisError

from app.shared import cache as cache_module

logger = structlog.get_logger("nanoboost.rate_limit")


async def check_rate_limit(*, key: str, limit: int, window_seconds: int) -> bool:
    """Return True if the caller is within the limit, False if exceeded.

    Uses INCR + EXPIRE: the first increment sets the TTL, subsequent
    increments only check the count. Redis-down or any RedisError
    short-circuits to "allowed" — losing rate-limit precision is
    preferable to 500-ing a legitimate submission.
    """
    client = await cache_module.get_client()
    if client is None:
        return True
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_seconds)
        return count <= limit
    except RedisError as exc:
        logger.warning("rate_limit_check_failed", key=key, error=str(exc))
        return True
