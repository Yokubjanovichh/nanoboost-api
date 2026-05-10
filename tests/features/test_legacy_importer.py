"""Tests for scripts/import_legacy_services.py.

Uses the SQLite test session and a small in-memory legacy snapshot. The full
real-world JSON (~19 services) lives at services-data.json (gitignored) — a
Manager-driven artifact, exercised in CI/staging when present.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.games.models import Game
from app.features.services.models import Service, ServiceOption
from scripts.import_legacy_services import import_into

pytestmark = pytest.mark.asyncio


# Compact stand-in for services-data.js: covers all fields that exercise
# the parser (titleHtml <br>, multi-platform, default option).
LEGACY_FIXTURE = {
    "gta-cash-cars-ps": {
        "seoTitle": "GTA Online Cash & Cars Boost PS4 / PS5",
        "seoDescription": "Buy GTA Online cash and cars boost for PS4 & PS5.",
        "titleHtml": "GTA Online Cash +<br>Cars Boost PS4/PS5",
        "imageSrc": "../assets/images/services3.webp",
        "imageAlt": "Buy GTA Online cash and cars boost",
        "platform": "PS4/PS5",
        "options": [
            "20 million - $15.99",
            "50 million - $29.99",
        ],
        "defaultOption": "20 million - $15.99",
        "eurOptions": [
            "20 million - €13.99",
            "50 million - €25.99",
        ],
        "description": [
            "Upgrade your GTA Online account.",
            "Get cash and premium cars.",
        ],
        "whatYouGet": [
            {
                "title": "Money Boost",
                "lead": "You can:",
                "items": ["Buy properties", "Unlock equipment"],
            }
        ],
        "sections": [
            {
                "title": "Designed for PlayStation",
                "texts": ["Optimized for PS4/PS5."],
            }
        ],
    },
    "gta-unlock-pc": {
        "seoTitle": "GTA Online Unlock All PC",
        "seoDescription": "Unlock everything in GTA Online for PC.",
        "titleHtml": "GTA Online Unlock All<br>PC",
        "imageSrc": "../assets/images/unlock-all.webp",
        "imageAlt": "GTA Online unlock all",
        "platform": "PC",
        "options": ["Unlock All - $29.99"],
        "defaultOption": "Unlock All - $29.99",
        "eurOptions": ["Unlock All - €25.99"],
        "description": ["Full PC unlock."],
        "whatYouGet": [],
        "sections": [],
    },
}


async def test_dry_run_creates_nothing(db_session: AsyncSession) -> None:
    summary = await import_into(
        db_session,
        LEGACY_FIXTURE,
        default_game_slug="gta5",
        game_name="GTA 5 Online",
        create_game_if_missing=True,
        dry_run=True,
    )
    assert summary["would-create"] == 2
    assert summary["created"] == 0

    # Rolled back — nothing persisted
    services = (await db_session.execute(select(Service))).scalars().all()
    assert services == []


async def test_real_run_creates_services_and_options(
    db_session: AsyncSession,
) -> None:
    summary = await import_into(
        db_session,
        LEGACY_FIXTURE,
        default_game_slug="gta5",
        game_name="GTA 5 Online",
        create_game_if_missing=True,
        dry_run=False,
    )
    assert summary["created"] == 2
    assert summary["options"] == 3  # 2 + 1

    # Game auto-created
    game = (
        await db_session.execute(select(Game).where(Game.slug == "gta5"))
    ).scalar_one()
    assert game.name == "GTA 5 Online"
    assert game.is_active is True

    services = (await db_session.execute(select(Service))).scalars().all()
    assert {s.slug for s in services} == {"gta-cash-cars-ps", "gta-unlock-pc"}

    cash = next(s for s in services if s.slug == "gta-cash-cars-ps")
    # Title <br> stripped
    assert cash.title == "GTA Online Cash + Cars Boost PS4/PS5"
    # SEO preserved
    assert cash.seo_title and "Cash" in cash.seo_title
    # JSONB columns populated
    assert len(cash.description) == 2
    assert cash.what_you_get[0]["title"] == "Money Boost"
    assert cash.sections[0]["title"] == "Designed for PlayStation"
    # Image migration intentionally skipped
    assert cash.image_url is None


async def test_default_option_marked(db_session: AsyncSession) -> None:
    await import_into(
        db_session,
        LEGACY_FIXTURE,
        default_game_slug="gta5",
        game_name="GTA 5 Online",
        create_game_if_missing=True,
        dry_run=False,
    )
    cash_service = (
        await db_session.execute(
            select(Service).where(Service.slug == "gta-cash-cars-ps")
        )
    ).scalar_one()

    options = (
        await db_session.execute(
            select(ServiceOption)
            .where(ServiceOption.service_id == cash_service.id)
            .order_by(ServiceOption.sort_order)
        )
    ).scalars().all()

    assert len(options) == 2
    assert options[0].label == "20 million"
    assert options[0].price_usd == Decimal("15.99")
    assert options[0].price_eur == Decimal("13.99")
    assert options[0].is_default is True
    assert options[1].is_default is False


async def test_idempotent_skip_on_rerun(db_session: AsyncSession) -> None:
    first = await import_into(
        db_session,
        LEGACY_FIXTURE,
        default_game_slug="gta5",
        game_name="GTA 5 Online",
        create_game_if_missing=True,
        dry_run=False,
    )
    assert first["created"] == 2

    second = await import_into(
        db_session,
        LEGACY_FIXTURE,
        default_game_slug="gta5",
        game_name="GTA 5 Online",
        create_game_if_missing=False,
        dry_run=False,
    )
    assert second["created"] == 0
    assert second["skipped"] == 2


async def test_missing_game_without_flag_aborts(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(RuntimeError, match="not found"):
        await import_into(
            db_session,
            LEGACY_FIXTURE,
            default_game_slug="never-existed",
            game_name="Whatever",
            create_game_if_missing=False,
            dry_run=True,
        )


async def test_unknown_platform_logs_and_skips(
    db_session: AsyncSession, caplog
) -> None:
    bad_payload = {
        "broken-svc": {
            "titleHtml": "Broken",
            "platform": "PSX",  # not in _PLATFORM_MAP
            "options": [],
            "eurOptions": [],
            "defaultOption": "",
            "description": [],
            "whatYouGet": [],
            "sections": [],
        }
    }
    summary = await import_into(
        db_session,
        bad_payload,
        default_game_slug="gta5",
        game_name="GTA 5 Online",
        create_game_if_missing=True,
        dry_run=False,
    )
    assert summary["created"] == 0
    # Nothing persisted for the broken slug
    rows = (
        await db_session.execute(
            select(Service).where(Service.slug == "broken-svc")
        )
    ).scalars().all()
    assert rows == []
