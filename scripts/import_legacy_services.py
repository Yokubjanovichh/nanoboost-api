"""Phase 7 outline — legacy services-data.js → Postgres importer.

This script will replace the inline `window.NB_SERVICE_CONFIG` object that
currently lives in frontend `scripts/services-data.js` with a real backend
load. The strategy is two-stage:

  1) Frontend exports the JS object once as JSON
     (one-off `node -e "console.log(JSON.stringify(NB_SERVICE_CONFIG))"`
     or a small browser snippet — reduces the parse problem to a regular
     `json.load`).

  2) This script reads the JSON file, deduplicates Game rows, creates
     Service + ServiceOption rows, and prints a summary. Idempotent:
     re-runs upsert by `slug`.

Usage (when Manager hands the JSON file):
    python -m scripts.import_legacy_services \\
        --input services-data.json \\
        [--dry-run] [--default-game-slug gta5]

PRECONDITIONS:
  * Phase 6 schema is current (services + service_options exist)
  * `Game` row for "gta5" already exists, OR `--default-game-slug` will
    be looked up / inserted automatically.

OUT OF SCOPE (Phase 7 detailed TZ):
  * Image asset migration — `imageSrc` paths still point to
    `../assets/images/...`. The frontend keeps serving those statically.
    A later iteration may upload them to /uploads/services/ and rewrite
    URLs.
  * `defaultOption` parsing edge cases (label vs full string).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.constants import Platform
from app.db.session import AsyncSessionLocal
from app.features.games.models import Game
from app.features.services.models import Service, ServiceOption

logger = logging.getLogger("nanoboost.import_legacy")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# Frontend `platform` strings → Backend Platform enum.
_PLATFORM_MAP = {
    "PS4/PS5": Platform.PS,
    "PS": Platform.PS,
    "Xbox One/Series": Platform.XBOX,
    "Xbox": Platform.XBOX,
    "PC": Platform.PC,
}

# Each slug pattern in services-data.js encodes the platform:
# `gta-cash-ps`, `gta-cash-xbox`, `gta-unlock-pc`, ...
# We don't rely on the trailing token alone — `platform` field is canonical.

_PRICE_USD_RE = re.compile(r"\$([\d.]+)")
_PRICE_EUR_RE = re.compile(r"€([\d.]+)")
_LABEL_RE = re.compile(r"^(.*?)\s*-\s*[\$€][\d.]+\s*$")


def _strip_html(value: str | None) -> str:
    """Defensive — strip <br> from any user-facing text field.

    services-data.js currently uses <br> only in `titleHtml`, but applying
    the strip universally protects against future drift in description /
    items / texts arrays.
    """
    if not value:
        return ""
    return re.sub(r"<br\s*/?>", " ", value).strip()


def _clean_list(items) -> list[str]:
    return [_strip_html(s) for s in (items or []) if isinstance(s, str)]


def _parse_option_pair(usd_str: str, eur_str: str) -> tuple[str, Decimal, Decimal]:
    """Returns (label, price_usd, price_eur).

    USD format:  "20 million - $15.99"
    EUR format:  "20 million - €13.99"
    Labels MUST match across the two arrays — sanity-check that.
    """
    usd_m = _PRICE_USD_RE.search(usd_str)
    eur_m = _PRICE_EUR_RE.search(eur_str)
    if usd_m is None or eur_m is None:
        raise ValueError(f"Cannot parse prices: {usd_str!r} / {eur_str!r}")

    label_m = _LABEL_RE.match(usd_str)
    label = (label_m.group(1) if label_m else usd_str).strip()

    eur_label_m = _LABEL_RE.match(eur_str)
    eur_label = (eur_label_m.group(1) if eur_label_m else eur_str).strip()
    if label != eur_label:
        raise ValueError(f"USD/EUR option labels diverge: {label!r} vs {eur_label!r}")

    return (
        label,
        Decimal(usd_m.group(1)),
        Decimal(eur_m.group(1)),
    )


def _expected_platform(legacy: dict) -> Platform:
    raw = legacy.get("platform", "")
    mapped = _PLATFORM_MAP.get(raw)
    if mapped is None:
        raise ValueError(f"Unknown platform string: {raw!r}")
    return mapped


async def _ensure_game(db, *, slug: str, name: str, create_if_missing: bool) -> Game:
    found = (await db.execute(select(Game).where(Game.slug == slug))).scalar_one_or_none()
    if found is not None:
        return found
    if not create_if_missing:
        raise RuntimeError(
            f"Game with slug={slug!r} not found. Pass --create-game-if-missing to auto-create it."
        )
    game = Game(slug=slug, name=name, is_active=True)
    db.add(game)
    await db.flush()
    return game


async def _upsert_service(
    db, *, game: Game, slug: str, legacy: dict, dry_run: bool
) -> tuple[str, int]:
    """Returns (action, options_inserted) where action ∈ {created, updated, skipped}."""
    title = _strip_html(legacy.get("titleHtml")) or slug
    platform = _expected_platform(legacy)

    existing = (await db.execute(select(Service).where(Service.slug == slug))).scalar_one_or_none()

    if existing is not None:
        # Conservative: don't touch existing services on re-run.
        return ("skipped", 0)

    if dry_run:
        return ("would-create", len(legacy.get("options", [])))

    service = Service(
        game_id=game.id,
        slug=slug,
        title=title,
        platform=platform,
        image_desktop_url=None,  # static frontend path — left as None for now
        image_mobile_url=None,
        image_alt=legacy.get("imageAlt"),
        description=_clean_list(legacy.get("description")),
        what_you_get=[
            {
                "title": _strip_html(item.get("title")),
                "lead": _strip_html(item.get("lead", "")),
                "items": _clean_list(item.get("items")),
            }
            for item in legacy.get("whatYouGet") or []
        ],
        sections=[
            {
                "title": _strip_html(item.get("title")),
                "texts": _clean_list(item.get("texts")),
            }
            for item in legacy.get("sections") or []
        ],
        seo_title=_strip_html(legacy.get("seoTitle")) or None,
        seo_description=_strip_html(legacy.get("seoDescription")) or None,
        is_active=True,
        is_featured=False,
        sort_order=0,
    )

    options_pairs = list(
        zip(
            legacy.get("options") or [],
            legacy.get("eurOptions") or [],
            strict=True,
        )
    )
    default_label = _LABEL_RE.match(legacy.get("defaultOption", "")) or _LABEL_RE.match("")
    default_text = (
        default_label.group(1).strip() if default_label and default_label.group(0) else ""
    )

    inserted = 0
    for sort_idx, (usd_str, eur_str) in enumerate(options_pairs):
        label, usd, eur = _parse_option_pair(usd_str, eur_str)
        service.options.append(
            ServiceOption(
                label=label,
                price_usd=usd,
                price_eur=eur,
                is_default=(label == default_text),
                sort_order=sort_idx,
            )
        )
        inserted += 1

    db.add(service)
    await db.flush()
    return ("created", inserted)


async def import_into(
    db,
    raw: dict,
    *,
    default_game_slug: str,
    game_name: str,
    create_game_if_missing: bool,
    dry_run: bool,
) -> dict:
    """Run the importer against a caller-supplied AsyncSession.

    Returns the summary dict so tests and the CLI both reuse the same path.
    """
    summary = {"created": 0, "skipped": 0, "would-create": 0, "options": 0}

    game = await _ensure_game(
        db,
        slug=default_game_slug,
        name=game_name,
        create_if_missing=create_game_if_missing,
    )
    for slug, legacy in raw.items():
        try:
            action, opts = await _upsert_service(
                db, game=game, slug=slug, legacy=legacy, dry_run=dry_run
            )
        except Exception:
            logger.exception("Failed for slug=%s", slug)
            continue

        summary[action] = summary.get(action, 0) + 1
        summary["options"] += opts
        logger.info("%-12s %s (+%d options)", action, slug, opts)

    if dry_run:
        await db.rollback()
        logger.info("Dry run — rollback complete")
    else:
        await db.commit()

    return summary


async def run(
    *,
    input_path: Path,
    default_game_slug: str,
    game_name: str,
    create_game_if_missing: bool,
    dry_run: bool,
) -> None:
    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        sys.exit(1)

    raw = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        logger.error("Expected top-level JSON object {slug: {...}}")
        sys.exit(1)

    async with AsyncSessionLocal() as db:
        summary = await import_into(
            db,
            raw,
            default_game_slug=default_game_slug,
            game_name=game_name,
            create_game_if_missing=create_game_if_missing,
            dry_run=dry_run,
        )

    logger.info("Summary: %s", summary)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Import legacy services-data.js into DB")
    p.add_argument("--input", type=Path, required=True, help="services-data.json")
    p.add_argument(
        "--default-game-slug",
        default="gta5",
        help="Game.slug to attach all services to",
    )
    p.add_argument(
        "--game-name",
        default="GTA 5 Online",
        help="Used only when the game row is auto-created",
    )
    p.add_argument(
        "--create-game-if-missing",
        action="store_true",
        help="Create the Game row if not found (otherwise abort)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate; rollback at the end",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(
        run(
            input_path=args.input,
            default_game_slug=args.default_game_slug,
            game_name=args.game_name,
            create_game_if_missing=args.create_game_if_missing,
            dry_run=args.dry_run,
        )
    )
