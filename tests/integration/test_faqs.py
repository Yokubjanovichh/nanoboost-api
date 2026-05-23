"""Per-game FAQ CRUD + RBAC + public read shape.

Coverage:
  * Public GET — active only, ordered, empty-list for unknown slug
  * Admin POST/PATCH/DELETE round-trip
  * Reorder bulk update
  * RBAC: anonymous → 401, viewer → 403, manager → 200, admin → 200
  * Cross-slug isolation (1 game's FAQs don't leak to another)
"""

from __future__ import annotations

import pytest

from app.features.faqs.models import GameFAQ


async def _seed_faq(
    db,
    *,
    game_slug: str,
    question: str,
    answer: str = "Default answer.",
    order_index: int = 0,
    is_active: bool = True,
) -> GameFAQ:
    faq = GameFAQ(
        game_slug=game_slug,
        question=question,
        answer=answer,
        order_index=order_index,
        is_active=is_active,
    )
    db.add(faq)
    await db.commit()
    await db.refresh(faq)
    return faq


# --- Public read path ----------------------------------------------------


@pytest.mark.asyncio
async def test_public_list_returns_active_only_in_order(client_with_db, db_session):
    await _seed_faq(db_session, game_slug="gta5", question="Q1", order_index=2)
    await _seed_faq(db_session, game_slug="gta5", question="Q2", order_index=0)
    await _seed_faq(db_session, game_slug="gta5", question="Hidden", order_index=1, is_active=False)

    res = await client_with_db.get("/api/v1/games/gta5/faqs")
    assert res.status_code == 200
    body = res.json()
    assert [f["question"] for f in body["faqs"]] == ["Q2", "Q1"]
    # Inactive row never reaches the wire.
    assert all("Hidden" != f["question"] for f in body["faqs"])


@pytest.mark.asyncio
async def test_public_list_unknown_slug_returns_empty_not_404(client_with_db):
    res = await client_with_db.get("/api/v1/games/no-such-game/faqs")
    assert res.status_code == 200
    assert res.json() == {"faqs": []}


@pytest.mark.asyncio
async def test_public_list_isolates_other_games(client_with_db, db_session):
    await _seed_faq(db_session, game_slug="gta5", question="GTA-only")
    await _seed_faq(db_session, game_slug="fh6", question="FH6-only")

    res = await client_with_db.get("/api/v1/games/gta5/faqs")
    assert res.status_code == 200
    questions = [f["question"] for f in res.json()["faqs"]]
    assert "GTA-only" in questions
    assert "FH6-only" not in questions


# --- Admin: create -------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_create_as_manager(client_with_db, manager_user, auth_headers):
    res = await client_with_db.post(
        "/api/v1/admin/games/gta5/faqs",
        headers=auth_headers(manager_user),
        json={"question": "How long?", "answer": "About 24h.", "order_index": 1},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["game_slug"] == "gta5"
    assert body["question"] == "How long?"
    assert body["order_index"] == 1
    assert body["is_active"] is True
    assert "created_at" in body and "updated_at" in body


@pytest.mark.asyncio
async def test_admin_create_requires_auth(client_with_db):
    res = await client_with_db.post(
        "/api/v1/admin/games/gta5/faqs",
        json={"question": "Q", "answer": "A"},
    )
    # No bearer token → the auth dep rejects with 401.
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_admin_create_rejects_viewer(client_with_db, viewer_user, auth_headers):
    res = await client_with_db.post(
        "/api/v1/admin/games/gta5/faqs",
        headers=auth_headers(viewer_user),
        json={"question": "Q", "answer": "A"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_admin_create_rejects_oversize_question(client_with_db, manager_user, auth_headers):
    res = await client_with_db.post(
        "/api/v1/admin/games/gta5/faqs",
        headers=auth_headers(manager_user),
        json={"question": "x" * 501, "answer": "A"},
    )
    assert res.status_code == 422


# --- Admin: list (includes inactive) -------------------------------------


@pytest.mark.asyncio
async def test_admin_list_includes_inactive(client_with_db, manager_user, db_session, auth_headers):
    await _seed_faq(db_session, game_slug="gta5", question="Active", is_active=True)
    await _seed_faq(db_session, game_slug="gta5", question="Inactive", is_active=False)

    res = await client_with_db.get(
        "/api/v1/admin/games/gta5/faqs",
        headers=auth_headers(manager_user),
    )
    assert res.status_code == 200
    questions = {f["question"] for f in res.json()}
    assert questions == {"Active", "Inactive"}


# --- Admin: update -------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_patch_toggles_active_flag(
    client_with_db, manager_user, db_session, auth_headers
):
    faq = await _seed_faq(db_session, game_slug="gta5", question="Q")

    res = await client_with_db.patch(
        f"/api/v1/admin/faqs/{faq.id}",
        headers=auth_headers(manager_user),
        json={"is_active": False},
    )
    assert res.status_code == 200
    assert res.json()["is_active"] is False
    # Question/answer untouched by a partial patch.
    assert res.json()["question"] == "Q"


@pytest.mark.asyncio
async def test_admin_patch_404_for_unknown_id(client_with_db, manager_user, auth_headers):
    res = await client_with_db.patch(
        "/api/v1/admin/faqs/999999",
        headers=auth_headers(manager_user),
        json={"is_active": False},
    )
    assert res.status_code == 404


# --- Admin: delete -------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_delete_as_admin(client_with_db, admin_user, db_session, auth_headers):
    faq = await _seed_faq(db_session, game_slug="gta5", question="Q")

    res = await client_with_db.delete(
        f"/api/v1/admin/faqs/{faq.id}",
        headers=auth_headers(admin_user),
    )
    assert res.status_code == 204

    # Public list no longer surfaces it.
    public = await client_with_db.get("/api/v1/games/gta5/faqs")
    assert public.json()["faqs"] == []


@pytest.mark.asyncio
async def test_admin_delete_rejects_manager(client_with_db, manager_user, db_session, auth_headers):
    """Same posture as the games soft-delete: hard deletes need admin+."""
    faq = await _seed_faq(db_session, game_slug="gta5", question="Q")

    res = await client_with_db.delete(
        f"/api/v1/admin/faqs/{faq.id}",
        headers=auth_headers(manager_user),
    )
    assert res.status_code == 403


# --- Admin: reorder ------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_reorder_swaps_order_indices(
    client_with_db, manager_user, db_session, auth_headers
):
    a = await _seed_faq(db_session, game_slug="gta5", question="A", order_index=0)
    b = await _seed_faq(db_session, game_slug="gta5", question="B", order_index=1)

    res = await client_with_db.post(
        "/api/v1/admin/games/gta5/faqs/reorder",
        headers=auth_headers(manager_user),
        json={"order": [{"id": a.id, "order_index": 1}, {"id": b.id, "order_index": 0}]},
    )
    assert res.status_code == 200
    assert res.json()["updated"] == 2

    public = await client_with_db.get("/api/v1/games/gta5/faqs")
    questions = [f["question"] for f in public.json()["faqs"]]
    assert questions == ["B", "A"]


@pytest.mark.asyncio
async def test_admin_reorder_ignores_other_games_ids(
    client_with_db, manager_user, db_session, auth_headers
):
    """Sending a foreign game's FAQ id must NOT renumber it — the
    repo's `WHERE game_slug=?` predicate is the safety net."""
    gta_faq = await _seed_faq(db_session, game_slug="gta5", question="GTA")
    fh_faq = await _seed_faq(db_session, game_slug="fh6", question="FH", order_index=99)

    res = await client_with_db.post(
        "/api/v1/admin/games/gta5/faqs/reorder",
        headers=auth_headers(manager_user),
        json={"order": [{"id": fh_faq.id, "order_index": 0}, {"id": gta_faq.id, "order_index": 5}]},
    )
    assert res.status_code == 200
    # Only the GTA-owned id counted.
    assert res.json()["updated"] == 1

    # FH FAQ's order is untouched.
    await db_session.refresh(fh_faq)
    assert fh_faq.order_index == 99
