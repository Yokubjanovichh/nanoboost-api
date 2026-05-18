"""Structured request logging — middleware, request_id, scrubbing.

Log-content tests read stdout via `capsys` because our formatter sits
on the root logger handler — pytest's `caplog` plugin sees the raw
structlog event dict, not the JSON-rendered line that actually ships
to Railway.
"""

from __future__ import annotations

import json
import re
import uuid

import pytest
import structlog

from app.shared.logging import configure_logging
from app.shared.middleware.request_logging import redact_headers

UUID_HEX_RE = re.compile(r"^[a-f0-9]{32}$")


def _json_events_from_stdout(captured: str) -> list[dict]:
    """Filter the captured stdout for JSON lines, ignore the rest
    (uvicorn / sqlalchemy noise that may bypass our renderer in tests)."""
    out = []
    for line in captured.splitlines():
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


@pytest.fixture
def json_logs(monkeypatch):
    """Force JSON output for the test, restore on teardown so the next
    test isn't affected."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    configure_logging()
    yield
    # Reset to default so subsequent tests aren't pinned to JSON.
    monkeypatch.setattr(settings, "LOG_FORMAT", "auto")
    configure_logging()


# --- X-Request-ID + correlation -------------------------------------------


@pytest.mark.asyncio
async def test_request_id_header_present_and_unique(client):
    r1 = await client.get("/health")
    r2 = await client.get("/health")
    rid1 = r1.headers["x-request-id"]
    rid2 = r2.headers["x-request-id"]
    assert UUID_HEX_RE.match(rid1)
    assert UUID_HEX_RE.match(rid2)
    assert rid1 != rid2


@pytest.mark.asyncio
async def test_inbound_request_id_is_preserved(client):
    forced = uuid.uuid4().hex
    r = await client.get("/health", headers={"X-Request-ID": forced})
    # Client-supplied ID echoes back so distributed traces correlate.
    assert r.headers["x-request-id"] == forced


# --- Header scrubbing ------------------------------------------------------


def test_redact_headers_blocks_sensitive_keys():
    safe = redact_headers(
        {
            "Authorization": "Bearer secret-token-XYZ",
            "Cookie": "session=abc",
            "X-Webhook-Signature": "sig",
            "Content-Type": "application/json",
            "User-Agent": "curl/8.0",
        }
    )
    assert safe["Authorization"] == "[REDACTED]"
    assert safe["Cookie"] == "[REDACTED]"
    assert safe["X-Webhook-Signature"] == "[REDACTED]"
    # Non-sensitive headers pass through unchanged.
    assert safe["Content-Type"] == "application/json"
    assert safe["User-Agent"] == "curl/8.0"


def test_redact_headers_case_insensitive():
    assert redact_headers({"authorization": "x"})["authorization"] == "[REDACTED]"
    assert redact_headers({"AUTHORIZATION": "x"})["AUTHORIZATION"] == "[REDACTED]"


# --- JSON formatter --------------------------------------------------------


def test_json_formatter_renders_one_line_per_record(json_logs, capsys):
    logger = structlog.get_logger("test.formatter")
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="abc123", user_id=None)

    logger.info("auth_login_success", email="x@y.io")

    events = _json_events_from_stdout(capsys.readouterr().out)
    match = next(e for e in events if e.get("event") == "auth_login_success")
    assert match["request_id"] == "abc123"
    assert match["email"] == "x@y.io"
    assert match["level"] == "info"
    assert "timestamp" in match
    structlog.contextvars.clear_contextvars()


def test_pretty_formatter_does_not_emit_json(monkeypatch, capsys):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LOG_FORMAT", "pretty")
    configure_logging()
    structlog.get_logger("test.pretty").info("hello", k="v")
    out = capsys.readouterr().out
    assert "hello" in out
    # No JSON-shaped line should appear in pretty mode.
    assert _json_events_from_stdout(out) == []
    monkeypatch.setattr(settings, "LOG_FORMAT", "auto")
    configure_logging()


# --- Request lifecycle logs ------------------------------------------------


@pytest.mark.asyncio
async def test_request_lifecycle_emits_start_and_completed(json_logs, client, capsys):
    r = await client.get("/health")
    events = _json_events_from_stdout(capsys.readouterr().out)
    started = [e for e in events if e.get("event") == "request_started"]
    completed = [e for e in events if e.get("event") == "request_completed"]
    assert started, "no request_started event emitted"
    assert completed, "no request_completed event emitted"
    last = completed[-1]
    assert last["status"] == 200
    assert last["method"] == "GET"
    assert last["path"] == "/health"
    assert isinstance(last["duration_ms"], int)
    assert last["request_id"] == r.headers["x-request-id"]


# --- Auth context binding --------------------------------------------------


@pytest.mark.asyncio
async def test_user_id_in_log_context_for_authenticated_request(
    json_logs, client_with_db, admin_user, auth_headers, capsys
):
    await client_with_db.get("/api/v1/auth/me", headers=auth_headers(admin_user))
    events = _json_events_from_stdout(capsys.readouterr().out)
    completed = next(e for e in events if e.get("event") == "request_completed")
    assert completed["user_id"] == str(admin_user.id)


@pytest.mark.asyncio
async def test_user_id_is_null_for_anonymous_request(json_logs, client, capsys):
    await client.get("/health")
    events = _json_events_from_stdout(capsys.readouterr().out)
    completed = next(e for e in events if e.get("event") == "request_completed")
    assert completed["user_id"] is None


@pytest.mark.asyncio
async def test_invalid_token_does_not_raise_in_middleware(client):
    """Middleware must never reject a request — bad tokens are the
    route dep's problem. user_id stays None."""
    r = await client.get(
        "/health",
        headers={"Authorization": "Bearer not.a.valid.jwt"},
    )
    assert r.status_code == 200
