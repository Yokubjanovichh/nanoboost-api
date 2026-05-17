"""In-process scheduler for background sweeps.

APScheduler runs inside the FastAPI process so we don't need a separate
worker/cron. Single replica today; if we ever horizontally scale, this
either moves to Railway's scheduled tasks or gains a DB-backed JobStore
to coordinate across instances.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.features.orders.service import OrderService

logger = logging.getLogger("nanoboost.scheduler")

scheduler = AsyncIOScheduler(timezone="UTC")


async def _cancel_stale_pending_orders() -> None:
    async with AsyncSessionLocal() as db:
        cancelled = await OrderService(db).cancel_stale_pending(
            hours=settings.AUTO_CANCEL_PENDING_HOURS,
        )
    if cancelled:
        logger.info("Auto-cancelled %d stale pending order(s)", cancelled)


def configure_jobs() -> None:
    """Register jobs based on current settings. Idempotent — `replace_existing`
    means re-calling won't pile up duplicate triggers (matters for tests
    that drive lifespan more than once).
    """
    if not settings.AUTO_CANCEL_PENDING_ENABLED:
        logger.info("AUTO_CANCEL_PENDING_ENABLED is False — skipping job registration")
        return

    scheduler.add_job(
        _cancel_stale_pending_orders,
        trigger="interval",
        hours=settings.AUTO_CANCEL_INTERVAL_HOURS,
        id="cancel_stale_pending_orders",
        replace_existing=True,
        coalesce=True,  # collapse missed runs into one
        max_instances=1,
    )
    logger.info(
        "Scheduled cancel_stale_pending_orders every %dh (cutoff: %dh)",
        settings.AUTO_CANCEL_INTERVAL_HOURS,
        settings.AUTO_CANCEL_PENDING_HOURS,
    )


def start() -> None:
    configure_jobs()
    if scheduler.get_jobs():
        scheduler.start()
        logger.info("Scheduler started")


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
