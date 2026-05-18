"""Per-request structured logging.

Generates a request_id, binds it (plus method, path, client IP, and a
best-effort user_id) into structlog's context-vars, emits start / end
events, and writes an `X-Request-ID` response header so clients can
correlate.

Sensitive headers are never logged. We don't log request bodies in
this PR — bodies are the most common place secrets leak, and we
haven't audited every payload shape. If a future operator wants
body-level visibility they should opt in per-route, not globally.
"""

from __future__ import annotations

import contextlib
import time
import uuid

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.constants import TokenType
from app.core.exceptions import TokenInvalidError
from app.core.security import decode_token

logger = structlog.get_logger("nanoboost.request")

# Header names we must never emit verbatim. Compared lowercase; mirrors
# the case-insensitive header handling in Starlette.
_SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-webhook-signature",
        "x-ecomtrade24-signature",
    }
)


def _client_ip(request: Request) -> str | None:
    # Honour the proxy chain (Railway / Cloudflare). Fall back to the
    # raw socket peer if no header is present.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def _user_id_from_token(request: Request) -> str | None:
    """Best-effort: extract user_id from a Bearer token without raising.

    Middleware runs before route dependencies, so we can't reuse the
    auth dep here (it would 401 unauthenticated requests). A broken
    token just leaves user_id as None — the dep on the protected route
    will still reject the request.
    """
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    if not token:
        return None
    with contextlib.suppress(TokenInvalidError, Exception):
        payload = decode_token(token, TokenType.ACCESS)
        sub = payload.get("sub")
        return str(sub) if sub else None
    return None


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        client_ip = _client_ip(request)
        user_id = _user_id_from_token(request)

        # Bind once; every log emitted during this request (ours and
        # any third-party library that routes through stdlib logging)
        # picks these fields up via structlog's contextvars processor.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client_ip=client_ip,
            user_id=user_id,
        )

        start = time.perf_counter()
        logger.info("request_started")

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "request_failed",
                duration_ms=duration_ms,
                # Stack info comes in via the formatter processor chain.
            )
            structlog.contextvars.clear_contextvars()
            raise

        duration_ms = int((time.perf_counter() - start) * 1000)
        response.headers["X-Request-ID"] = request_id

        # 5xx is logged at error level so Railway alert rules can pick
        # them up; 4xx is a client problem, info-level is fine.
        log_method = logger.error if response.status_code >= 500 else logger.info
        log_method(
            "request_completed",
            status=response.status_code,
            duration_ms=duration_ms,
        )

        structlog.contextvars.clear_contextvars()
        return response


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Helper for ad-hoc header logging from other code paths."""
    return {k: ("[REDACTED]" if k.lower() in _SENSITIVE_HEADERS else v) for k, v in headers.items()}
