"""One-off: merge the duplicate `gta-5-online` Game row into `gta5`.

The duplicate was created by an early admin-panel save before slug
normalisation rules were enforced. Re-parents every Service that points
at the duplicate to the canonical row, then deletes the duplicate.

Idempotent: if either game is missing the script logs and exits cleanly,
so it's safe to re-run after a partial run or in environments where the
duplicate never existed.

Run AFTER migration 0009 has been applied:
    python -m scripts.cleanup_duplicate_games
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select, update

from app.db.session import AsyncSessionLocal
from app.features.games.models import Game
from app.features.services.models import Service

logger = logging.getLogger("nanoboost.cleanup_duplicate_games")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

OLD_SLUG = "gta-5-online"
NEW_SLUG = "gta5"


async def run() -> None:
    async with AsyncSessionLocal() as db:
        old = (await db.execute(select(Game).where(Game.slug == OLD_SLUG))).scalar_one_or_none()
        new = (await db.execute(select(Game).where(Game.slug == NEW_SLUG))).scalar_one_or_none()

        if old is None:
            logger.info("Nothing to merge: %r not found", OLD_SLUG)
            return
        if new is None:
            logger.error(
                "Refusing to delete %r: canonical %r is missing",
                OLD_SLUG,
                NEW_SLUG,
            )
            return
        if old.id == new.id:
            logger.info("Same row: nothing to do")
            return

        moved = (
            await db.execute(
                update(Service).where(Service.game_id == old.id).values(game_id=new.id)
            )
        ).rowcount or 0
        logger.info(
            "Re-parented %d services from %r -> %r",
            moved,
            OLD_SLUG,
            NEW_SLUG,
        )

        await db.delete(old)
        await db.commit()
        logger.info("Deleted duplicate game: %r", OLD_SLUG)


if __name__ == "__main__":
    asyncio.run(run())
