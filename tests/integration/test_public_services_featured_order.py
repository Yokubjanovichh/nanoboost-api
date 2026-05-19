"""Featured services land newest-first when admin hasn't reordered.

Pins the marketing requirement: marking a service Featured today
should put it at the top of "Hot Right Now" without renumbering the
catalogue. Manual `sort_order` still wins where it's been set."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.constants import Platform
from app.features.services.models import Service


async def _make_featured(db, *, game, slug, title, created_at, sort_order=0):
    svc = Service(
        game_id=game.id,
        slug=slug,
        title=title,
        platform=Platform.PS,
        description=["A line."],
        what_you_get=[],
        sections=[],
        is_featured=True,
        sort_order=sort_order,
        is_active=True,
        is_deleted=False,
        created_at=created_at,
    )
    db.add(svc)
    await db.commit()
    return svc


@pytest.mark.asyncio
async def test_featured_services_newest_first_when_sort_order_equal(
    client_with_db, db_session, sample_game
):
    """Default tie-break: created_at DESC. Newest Featured wins the
    top slot — the marketing-team-friendly behaviour."""
    now = datetime.now(UTC)
    await _make_featured(
        db_session,
        game=sample_game,
        slug="old-cash",
        title="Old",
        created_at=now - timedelta(days=10),
    )
    await _make_featured(
        db_session,
        game=sample_game,
        slug="mid-cash",
        title="Mid",
        created_at=now - timedelta(days=5),
    )
    await _make_featured(
        db_session,
        game=sample_game,
        slug="new-cash",
        title="New",
        created_at=now,
    )

    res = await client_with_db.get("/api/v1/public/services?featured=true")
    assert res.status_code == 200
    slugs = [s["slug"] for s in res.json()]
    assert slugs == ["new-cash", "mid-cash", "old-cash"]


@pytest.mark.asyncio
async def test_manual_sort_order_still_wins_over_created_at(
    client_with_db, db_session, sample_game
):
    """sort_order is the primary key — when admin pins something with
    a lower number, that wins even if it's the older row."""
    now = datetime.now(UTC)
    # `a` is older but has the lower sort_order → must come first.
    await _make_featured(
        db_session,
        game=sample_game,
        slug="a",
        title="A",
        sort_order=1,
        created_at=now - timedelta(days=1),
    )
    await _make_featured(
        db_session,
        game=sample_game,
        slug="b",
        title="B",
        sort_order=2,
        created_at=now,
    )

    res = await client_with_db.get("/api/v1/public/services?featured=true")
    assert res.status_code == 200
    slugs = [s["slug"] for s in res.json()]
    assert slugs == ["a", "b"]
