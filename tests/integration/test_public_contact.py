"""Integration tests for POST /api/v1/public/contact."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.features.clients.models import Client
from app.features.contact.models import ContactSubmission
from app.features.contact.notifier import ContactNotifier
from app.shared.notifications.base import NoOpBackend


def _valid_payload(**overrides):
    base = {
        "preferred_contact": "discord",
        "handle": "shadow#1234",
        "email": "shadow@example.com",
        "message": "Hi, I'd like to ask about a custom GTA boost setup.",
    }
    base.update(overrides)
    return base


# --- Happy path ------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_returns_ok_and_persists(client_with_db, db_session):
    res = await client_with_db.post(
        "/api/v1/public/contact",
        json=_valid_payload(),
    )
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    rows = (await db_session.execute(select(ContactSubmission))).scalars().all()
    assert len(rows) == 1
    sub = rows[0]
    assert sub.preferred_contact == "discord"
    assert sub.handle == "shadow#1234"
    assert sub.email == "shadow@example.com"
    assert sub.client_id is None  # no matching client seeded
    assert sub.ip_address is not None  # populated from test client peer


@pytest.mark.asyncio
async def test_submit_links_existing_client_by_email(client_with_db, db_session):
    existing = Client(email="loyal@example.com", discord="@loyal")
    db_session.add(existing)
    await db_session.commit()

    res = await client_with_db.post(
        "/api/v1/public/contact",
        json=_valid_payload(email="loyal@example.com"),
    )
    assert res.status_code == 200

    sub = (await db_session.execute(select(ContactSubmission))).scalar_one()
    assert sub.client_id == existing.id


@pytest.mark.asyncio
async def test_submit_without_email_leaves_client_null(client_with_db, db_session):
    payload = _valid_payload()
    payload.pop("email")
    res = await client_with_db.post("/api/v1/public/contact", json=payload)
    assert res.status_code == 200

    sub = (await db_session.execute(select(ContactSubmission))).scalar_one()
    assert sub.email is None
    assert sub.client_id is None


# --- Validation ------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_required_when_preferred_email(client_with_db):
    payload = _valid_payload(preferred_contact="email")
    payload.pop("email")
    res = await client_with_db.post("/api/v1/public/contact", json=payload)
    assert res.status_code == 422
    assert any(
        "email is required when preferred_contact" in (err.get("msg") or "")
        for err in res.json()["detail"]
    )


@pytest.mark.asyncio
async def test_short_message_rejected(client_with_db):
    res = await client_with_db.post(
        "/api/v1/public/contact",
        json=_valid_payload(message="too short"),  # < 10 chars after trim
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_whitespace_only_long_message_rejected(client_with_db):
    res = await client_with_db.post(
        "/api/v1/public/contact",
        json=_valid_payload(message=" " * 50),
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_oversized_message_rejected(client_with_db):
    res = await client_with_db.post(
        "/api/v1/public/contact",
        json=_valid_payload(message="x" * 2001),
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_unknown_preferred_contact_rejected(client_with_db):
    res = await client_with_db.post(
        "/api/v1/public/contact",
        json=_valid_payload(preferred_contact="signal"),
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_invalid_email_rejected(client_with_db):
    res = await client_with_db.post(
        "/api/v1/public/contact",
        json=_valid_payload(email="not-an-email"),
    )
    assert res.status_code == 422


# --- Notifier behaviour ----------------------------------------------------


def test_notifier_escapes_markdown_specials():
    """A handle / message with Markdown specials must not break Telegram
    parsing or sneak formatting into the notification."""
    notifier = ContactNotifier(telegram=NoOpBackend())
    sub = ContactSubmission(
        preferred_contact="discord",
        handle="evil_*[user]`",
        email="evil@example.com",
        message="hello *bold* `code` _italic_ [link](url)",
        client_id=None,
        ip_address=None,
        user_agent=None,
    )
    formatted = notifier.format(sub)
    # The dangerous characters from the user-supplied fields are stripped.
    for ch in ("*bold*", "`code`", "_italic_", "[link]", "evil_", "[user]"):
        assert ch not in formatted, f"unsafe substring leaked: {ch!r}"


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_threshold(client_with_db, fakeredis_client):
    """5 submissions per minute / IP. 6th must 429."""
    for i in range(5):
        res = await client_with_db.post(
            "/api/v1/public/contact",
            json=_valid_payload(message=f"Inquiry number {i} about boost services."),
        )
        assert res.status_code == 200, f"call #{i} unexpectedly failed: {res.text}"

    res = await client_with_db.post(
        "/api/v1/public/contact",
        json=_valid_payload(message="One more attempt right after the cap."),
    )
    assert res.status_code == 429
    assert "Too many requests" in res.json()["detail"]


@pytest.mark.asyncio
async def test_telegram_failure_does_not_break_endpoint(client_with_db, db_session, monkeypatch):
    """Background-task failures must not leak to the client. The
    submission must already be in the DB before the notify runs."""
    from app.features.contact import router as contact_router

    failing_backend = AsyncMock()
    failing_backend.send = AsyncMock(side_effect=RuntimeError("telegram down"))
    monkeypatch.setattr(
        contact_router,
        "get_telegram_backend",
        lambda: failing_backend,
    )

    res = await client_with_db.post(
        "/api/v1/public/contact",
        json=_valid_payload(),
    )
    assert res.status_code == 200

    sub = (await db_session.execute(select(ContactSubmission))).scalar_one()
    assert sub is not None
