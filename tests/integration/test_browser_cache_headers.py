"""Browser-side `Cache-Control` on /api/v1/public/*.

The Redis layer is tested elsewhere (`test_cache_endpoints.py` — that's
the server cache, surfaced via `X-Cache: HIT|MISS|BYPASS`). This file
covers what the *browser* sees: the `Cache-Control` header that
enables disk cache + `stale-while-revalidate` on page navigation.
"""

from __future__ import annotations

import pytest

from app.features.contact.models import ContactSubmission

# --- GET 200: Cache-Control present + correct shape -----------------------


@pytest.mark.asyncio
async def test_games_list_has_browser_cache_header(client):
    r = await client.get("/api/v1/public/games")
    assert r.status_code == 200
    cc = r.headers["cache-control"]
    assert "public" in cc
    assert "max-age=60" in cc
    assert "stale-while-revalidate=240" in cc


@pytest.mark.asyncio
async def test_services_list_has_browser_cache_header(client):
    r = await client.get("/api/v1/public/services")
    assert r.status_code == 200
    cc = r.headers["cache-control"]
    assert "max-age=60" in cc
    assert "stale-while-revalidate=120" in cc


@pytest.mark.asyncio
async def test_service_detail_gets_longer_max_age(client_with_db, sample_service):
    """Detail TTL is intentionally longer than the list TTL — fewer
    invalidations and the slug page is the natural deep-link."""
    r = await client_with_db.get(f"/api/v1/public/services/{sample_service.slug}")
    assert r.status_code == 200
    cc = r.headers["cache-control"]
    assert "max-age=120" in cc
    assert "stale-while-revalidate=180" in cc


@pytest.mark.asyncio
async def test_reviews_list_has_longest_max_age(client):
    r = await client.get("/api/v1/public/reviews")
    assert r.status_code == 200
    cc = r.headers["cache-control"]
    assert "max-age=300" in cc
    assert "stale-while-revalidate=600" in cc


# --- Non-200 GETs: must NOT inherit the cache header ----------------------


@pytest.mark.asyncio
async def test_validation_failure_does_not_carry_cache_header(client):
    """422 is browser-side garbage — don't let it pin a bad request
    shape in the disk cache."""
    r = await client.get("/api/v1/public/services?platform=switch")
    assert r.status_code == 422
    # Either no header at all, or explicitly defensive.
    assert "public, max-age" not in r.headers.get("cache-control", "")


@pytest.mark.asyncio
async def test_missing_service_404_not_cacheable(client_with_db):
    r = await client_with_db.get("/api/v1/public/services/does-not-exist")
    assert r.status_code == 404
    assert "public, max-age" not in r.headers.get("cache-control", "")


# --- Public mutations: no-store -------------------------------------------


@pytest.mark.asyncio
async def test_contact_post_is_no_store(client_with_db, db_session):
    r = await client_with_db.post(
        "/api/v1/public/contact",
        json={
            "preferred_contact": "discord",
            "handle": "shadow#1234",
            "message": "I'd like to ask about a custom GTA boost setup.",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"
    # Sanity: the mutation actually persisted; we're not just asserting
    # on a 422 that happens to be no-store.
    from sqlalchemy import select

    rows = (await db_session.execute(select(ContactSubmission))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_non_public_get_unaffected(client):
    """Health is outside /api/v1/public/* — middleware must not touch
    Cache-Control here. Anything that does is a scope bug."""
    r = await client.get("/health")
    assert r.status_code == 200
    assert "public, max-age" not in r.headers.get("cache-control", "")
