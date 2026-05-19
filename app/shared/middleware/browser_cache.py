"""Browser-side Cache-Control for read-only public endpoints.

Sits next to the Redis layer (`X-Cache: HIT/MISS/BYPASS`) — the Redis
cache cuts our DB round-trips, this middleware cuts the *network*
round-trips from the browser. `stale-while-revalidate` keeps page
navigation feeling instant: the browser serves the stale copy while
fetching a fresh one in the background.

Scope:
- Only `GET` requests get a positive Cache-Control. 4xx / 5xx and
  every non-GET response is left untouched (browsers shouldn't cache
  error envelopes or mutation responses).
- `POST` / `PATCH` / `DELETE` under `/api/v1/public/*` get
  `Cache-Control: no-store` to make sure no intermediate cache hangs
  onto an order receipt or a contact submission.

Adding a new public read endpoint? Add the prefix to `_GET_RULES` and
keep the more specific path first — the loop short-circuits on the
first prefix match.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

# More specific paths must come first so e.g. `/services/{slug}` wins
# over `/services` (the list endpoint).
_GET_RULES: tuple[tuple[str, str], ...] = (
    ("/api/v1/public/services/", "public, max-age=120, stale-while-revalidate=180"),
    ("/api/v1/public/services", "public, max-age=60, stale-while-revalidate=120"),
    ("/api/v1/public/games/", "public, max-age=60, stale-while-revalidate=240"),
    ("/api/v1/public/games", "public, max-age=60, stale-while-revalidate=240"),
    ("/api/v1/public/reviews", "public, max-age=300, stale-while-revalidate=600"),
)

_PUBLIC_PREFIX = "/api/v1/public/"


def _match_get_rule(path: str) -> str | None:
    for prefix, header in _GET_RULES:
        if path.startswith(prefix):
            return header
    return None


class BrowserCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next) -> Response:
        response: Response = await call_next(request)

        path = request.url.path

        # Mutation under /api/v1/public/* → never cache. The browser
        # would otherwise be free to keep an order-create response.
        if request.method != "GET" and path.startswith(_PUBLIC_PREFIX):
            response.headers.setdefault("Cache-Control", "no-store")
            return response

        # Only stamp Cache-Control on 200 GETs. 304 already carries
        # caching semantics from the previous response; 4xx/5xx must
        # not be cached.
        if request.method == "GET" and response.status_code == 200:
            header = _match_get_rule(path)
            if header is not None:
                # `setdefault` so an endpoint that wants stronger
                # semantics (e.g. immutable for uploads) keeps them.
                response.headers.setdefault("Cache-Control", header)

        return response


def install(app: ASGIApp) -> None:
    """Tiny helper so `app/main.py` doesn't grow another import line."""
    from fastapi import FastAPI

    assert isinstance(app, FastAPI)
    app.add_middleware(BrowserCacheMiddleware)
