"""Public games endpoint — service_count + status filter.

Pins the PR #13 contract: every game carries a service_count, hidden
games are excluded, and a game with zero services still appears (the
LEFT JOIN edge case that the previous query got wrong).
"""

from __future__ import annotations

import pytest

from app.core.constants import GameStatus, Platform
from app.features.games.models import Game
from app.features.services.models import Service


async def _seed(db, name, slug, status, n_active=0, n_inactive=0, n_deleted=0):
    game = Game(slug=slug, name=name, sort_order=0, status=status)
    db.add(game)
    await db.flush()
    for i in range(n_active):
        db.add(
            Service(
                game_id=game.id,
                slug=f"{slug}-a-{i}",
                title=f"{name} svc {i}",
                platform=Platform.PS,
                description=[],
                what_you_get=[],
                sections=[],
                is_featured=False,
                sort_order=i,
                is_active=True,
                is_deleted=False,
            )
        )
    for i in range(n_inactive):
        db.add(
            Service(
                game_id=game.id,
                slug=f"{slug}-i-{i}",
                title=f"{name} inactive {i}",
                platform=Platform.PS,
                description=[],
                what_you_get=[],
                sections=[],
                is_featured=False,
                sort_order=i,
                is_active=False,
                is_deleted=False,
            )
        )
    for i in range(n_deleted):
        db.add(
            Service(
                game_id=game.id,
                slug=f"{slug}-d-{i}",
                title=f"{name} deleted {i}",
                platform=Platform.PS,
                description=[],
                what_you_get=[],
                sections=[],
                is_featured=False,
                sort_order=i,
                is_active=True,
                is_deleted=True,
            )
        )
    await db.commit()
    return game


@pytest.mark.asyncio
async def test_service_count_includes_only_active_non_deleted(client_with_db, db_session):
    await _seed(
        db_session,
        "GTA 5",
        "gta5",
        GameStatus.ACTIVE,
        n_active=3,
        n_inactive=1,
        n_deleted=2,
    )
    res = await client_with_db.get("/api/v1/public/games")
    assert res.status_code == 200
    games = {g["slug"]: g for g in res.json()}
    assert games["gta5"]["service_count"] == 3


@pytest.mark.asyncio
async def test_zero_service_games_still_appear(client_with_db, db_session):
    """The LEFT JOIN bug: 0-service games used to collapse out."""
    await _seed(db_session, "Forza", "forza", GameStatus.ACTIVE)
    res = await client_with_db.get("/api/v1/public/games")
    games = {g["slug"]: g for g in res.json()}
    assert "forza" in games
    assert games["forza"]["service_count"] == 0


@pytest.mark.asyncio
async def test_coming_soon_games_visible_with_zero_count(client_with_db, db_session):
    await _seed(db_session, "WoW", "wow", GameStatus.COMING_SOON)
    res = await client_with_db.get("/api/v1/public/games")
    games = {g["slug"]: g for g in res.json()}
    assert games["wow"]["status"] == "coming_soon"
    assert games["wow"]["service_count"] == 0


@pytest.mark.asyncio
async def test_hidden_games_excluded(client_with_db, db_session):
    await _seed(db_session, "Hidden", "hidden-game", GameStatus.HIDDEN, n_active=5)
    res = await client_with_db.get("/api/v1/public/games")
    slugs = [g["slug"] for g in res.json()]
    assert "hidden-game" not in slugs
