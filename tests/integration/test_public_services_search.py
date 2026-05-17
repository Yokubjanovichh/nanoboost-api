"""Issue #13a — search + platform filter on /public/services."""

from __future__ import annotations

import pytest

from app.core.constants import Platform
from app.features.services.models import Service


async def _make_svc(db, game, *, slug, title, platform, description=None, sort=0):
    svc = Service(
        game_id=game.id,
        slug=slug,
        title=title,
        platform=platform,
        description=description or ["A line."],
        what_you_get=[],
        sections=[],
        is_featured=False,
        sort_order=sort,
        is_active=True,
        is_deleted=False,
    )
    db.add(svc)
    await db.commit()
    return svc


@pytest.fixture
async def seeded_services(db_session, sample_game):
    cash_ps = await _make_svc(
        db_session,
        sample_game,
        slug="gta-cash-ps",
        title="GTA Online Cash Boost",
        platform=Platform.PS,
        description=["Quick cash for GTA Online."],
        sort=0,
    )
    level_xbox = await _make_svc(
        db_session,
        sample_game,
        slug="gta-level-xbox",
        title="GTA Level Boost",
        platform=Platform.XBOX,
        description=["Level your account fast."],
        sort=1,
    )
    unlock_pc = await _make_svc(
        db_session,
        sample_game,
        slug="gta-unlock-pc",
        title="GTA Unlock All PC",
        platform=Platform.PC,
        description=["Unlock everything on PC."],
        sort=2,
    )
    return {"ps": cash_ps, "xbox": level_xbox, "pc": unlock_pc}


# --- Platform filter -------------------------------------------------------


@pytest.mark.asyncio
async def test_platform_ps_returns_only_ps(client_with_db, seeded_services):
    res = await client_with_db.get("/api/v1/public/services?platform=ps")
    assert res.status_code == 200
    slugs = [s["slug"] for s in res.json()]
    assert slugs == ["gta-cash-ps"]


@pytest.mark.asyncio
async def test_platform_uppercase_accepted(client_with_db, seeded_services):
    res = await client_with_db.get("/api/v1/public/services?platform=XBOX")
    assert res.status_code == 200
    slugs = [s["slug"] for s in res.json()]
    assert slugs == ["gta-level-xbox"]


@pytest.mark.asyncio
async def test_platform_mixed_case_accepted(client_with_db, seeded_services):
    res = await client_with_db.get("/api/v1/public/services?platform=Pc")
    assert res.status_code == 200
    slugs = [s["slug"] for s in res.json()]
    assert slugs == ["gta-unlock-pc"]


@pytest.mark.asyncio
async def test_platform_switch_rejected(client):
    res = await client.get("/api/v1/public/services?platform=switch")
    assert res.status_code == 422


# --- Search ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_matches_title_substring(client_with_db, seeded_services):
    res = await client_with_db.get("/api/v1/public/services?search=cash")
    assert res.status_code == 200
    slugs = [s["slug"] for s in res.json()]
    assert slugs == ["gta-cash-ps"]


@pytest.mark.asyncio
async def test_search_is_case_insensitive(client_with_db, seeded_services):
    res = await client_with_db.get("/api/v1/public/services?search=BOOST")
    assert res.status_code == 200
    # Two titles contain "boost" (Cash Boost + Level Boost).
    slugs = sorted(s["slug"] for s in res.json())
    assert slugs == ["gta-cash-ps", "gta-level-xbox"]


@pytest.mark.asyncio
async def test_search_matches_description(client_with_db, seeded_services):
    # "fast" appears only in level_xbox description, not in any title.
    res = await client_with_db.get("/api/v1/public/services?search=fast")
    assert res.status_code == 200
    slugs = [s["slug"] for s in res.json()]
    assert slugs == ["gta-level-xbox"]


@pytest.mark.asyncio
async def test_search_one_char_rejected(client):
    res = await client.get("/api/v1/public/services?search=c")
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_search_over_max_rejected(client):
    res = await client.get("/api/v1/public/services?search=" + "x" * 101)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_search_sql_injection_attempt_is_safe(client_with_db, seeded_services):
    # Single-quote + classic SQLi tail. Parameterised, so no rows match
    # this nonsense literal — and crucially no 500.
    res = await client_with_db.get("/api/v1/public/services?search=cash%27%20OR%20%271%27=%271")
    assert res.status_code == 200
    assert res.json() == []


# --- Combinations ----------------------------------------------------------


@pytest.mark.asyncio
async def test_game_platform_search_combine(client_with_db, seeded_services, sample_game):
    res = await client_with_db.get(
        f"/api/v1/public/services?game={sample_game.slug}&platform=ps&search=cash"
    )
    assert res.status_code == 200
    slugs = [s["slug"] for s in res.json()]
    assert slugs == ["gta-cash-ps"]


@pytest.mark.asyncio
async def test_combination_with_no_match_returns_empty(client_with_db, seeded_services):
    # PS service exists, but nothing PS matches "unlock".
    res = await client_with_db.get("/api/v1/public/services?platform=ps&search=unlock")
    assert res.status_code == 200
    assert res.json() == []


# --- Cache key includes search ---------------------------------------------


@pytest.mark.asyncio
async def test_same_search_query_caches_hit_then_miss_for_different(
    client_with_db, seeded_services, fakeredis_client
):
    """Identical (game, platform, search) combo → HIT on repeat. Different
    search query → MISS (separate cache key)."""
    first = await client_with_db.get("/api/v1/public/services?search=cash")
    assert first.headers["x-cache"] == "MISS"

    second = await client_with_db.get("/api/v1/public/services?search=cash")
    assert second.headers["x-cache"] == "HIT"
    assert second.content == first.content

    # Different search term → separate key → MISS.
    other = await client_with_db.get("/api/v1/public/services?search=level")
    assert other.headers["x-cache"] == "MISS"
