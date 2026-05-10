"""ON DELETE RESTRICT on Game→Service FK.

Soft delete (UPDATE games SET is_deleted = true) is fine.
Hard delete (DELETE FROM games WHERE id = ...) must fail with
IntegrityError when at least one Service still points at the game,
keeping the order/service history intact.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.constants import Platform
from app.features.games.models import Game
from app.features.services.models import Service

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_game_hard_delete_with_bound_service_raises(
    pg_session,
) -> None:
    game = Game(slug="restrict-game", name="Restrict")
    pg_session.add(game)
    await pg_session.commit()
    await pg_session.refresh(game)

    service = Service(
        game_id=game.id,
        slug="restrict-svc",
        title="Restrict Service",
        platform=Platform.PS,
        description=[],
        what_you_get=[],
        sections=[],
    )
    pg_session.add(service)
    await pg_session.commit()

    # Attempt hard delete — must fail because of ON DELETE RESTRICT.
    with pytest.raises(IntegrityError):
        await pg_session.execute(
            text("DELETE FROM games WHERE id = :id"),
            {"id": str(game.id)},
        )
        await pg_session.commit()
    await pg_session.rollback()


async def test_game_soft_delete_with_bound_service_succeeds(
    pg_session,
) -> None:
    game = Game(slug="soft-game", name="Soft")
    pg_session.add(game)
    await pg_session.commit()
    await pg_session.refresh(game)

    service = Service(
        game_id=game.id,
        slug="soft-svc",
        title="Soft Service",
        platform=Platform.PS,
        description=[],
        what_you_get=[],
        sections=[],
    )
    pg_session.add(service)
    await pg_session.commit()

    # Soft delete — UPDATE only, FK undisturbed.
    game.is_deleted = True
    await pg_session.commit()
    # No exception means RESTRICT did not fire; service survives intact.
    assert service.id is not None
