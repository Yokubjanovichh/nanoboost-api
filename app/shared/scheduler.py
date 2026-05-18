"""In-process scheduler for background sweeps.

APScheduler runs inside the FastAPI process so we don't need a separate
worker/cron. Single replica today; if we ever horizontally scale, this
either moves to Railway's scheduled tasks or gains a DB-backed JobStore
to coordinate across instances.
"""

from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.features.orders.service import OrderService

logger = structlog.get_logger("nanoboost.scheduler")

scheduler = AsyncIOScheduler(timezone="UTC")


async def _cancel_stale_pending_orders() -> None:
    logger.info("scheduler_job_started", job="cancel_stale_pending_orders")
    async with AsyncSessionLocal() as db:
        cancelled = await OrderService(db).cancel_stale_pending(
            hours=settings.AUTO_CANCEL_PENDING_HOURS,
        )
    logger.info(
        "scheduler_job_completed",
        job="cancel_stale_pending_orders",
        cancelled=cancelled,
    )


def configure_jobs() -> None:
    """Register jobs based on current settings. Idempotent — `replace_existing`
    means re-calling won't pile up duplicate triggers (matters for tests
    that drive lifespan more than once).
    """
    if not settings.AUTO_CANCEL_PENDING_ENABLED:
        logger.info("scheduler_disabled", reason="AUTO_CANCEL_PENDING_ENABLED=false")
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
        "scheduler_job_registered",
        job="cancel_stale_pending_orders",
        interval_hours=settings.AUTO_CANCEL_INTERVAL_HOURS,
        cutoff_hours=settings.AUTO_CANCEL_PENDING_HOURS,
    )


def start() -> None:
    configure_jobs()
    if scheduler.get_jobs():
        scheduler.start()
        logger.info("scheduler_started")


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")
