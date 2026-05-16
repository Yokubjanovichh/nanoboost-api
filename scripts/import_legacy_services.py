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
from sqlalchemy.orm import selectinload

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


def _normalise_image_src(image_src: str | None) -> str | None:
    """Rewrite the legacy frontend asset path into the public-site URL form.

    services-data.js stores paths like "../assets/images/services3.webp" — a
    path relative to /pages/*.html. We strip the "../" and keep the
    "/assets/images/..." form so the public site can resolve it from root.
    Admins replace these with /uploads/services/... URLs once the proper
    image is uploaded via the admin panel.
    """
    if not image_src:
        return None
    cleaned = image_src.strip()
    if not cleaned:
        return None
    while cleaned.startswith("../"):
        cleaned = cleaned[3:]
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if not cleaned.startswith(("/", "http://", "https://")):
        cleaned = "/" + cleaned
    return cleaned


def _build_service_payload(legacy: dict) -> dict:
    """Shared field map used by both INSERT and UPDATE branches."""
    return {
        "title": _strip_html(legacy.get("titleHtml")) or "",
        "platform": _expected_platform(legacy),
        "image_desktop_url": _normalise_image_src(legacy.get("imageSrc")),
        "image_mobile_url": None,
        "image_alt": legacy.get("imageAlt"),
        "description": _clean_list(legacy.get("description")),
        "what_you_get": [
            {
                "title": _strip_html(item.get("title")),
                "lead": _strip_html(item.get("lead", "")),
                "items": _clean_list(item.get("items")),
            }
            for item in legacy.get("whatYouGet") or []
        ],
        "sections": [
            {
                "title": _strip_html(item.get("title")),
                "texts": _clean_list(item.get("texts")),
            }
            for item in legacy.get("sections") or []
        ],
        "seo_title": _strip_html(legacy.get("seoTitle")) or None,
        "seo_description": _strip_html(legacy.get("seoDescription")) or None,
    }


def _build_options(legacy: dict) -> list[tuple[str, Decimal, Decimal, bool, int]]:
    """Returns [(label, usd, eur, is_default, sort_order), ...]."""
    options_pairs = list(
        zip(
            legacy.get("options") or [],
            legacy.get("eurOptions") or [],
            strict=True,
        )
    )
    default_match = _LABEL_RE.match(legacy.get("defaultOption", "") or "")
    default_text = default_match.group(1).strip() if default_match else ""

    out: list[tuple[str, Decimal, Decimal, bool, int]] = []
    for sort_idx, (usd_str, eur_str) in enumerate(options_pairs):
        label, usd, eur = _parse_option_pair(usd_str, eur_str)
        out.append((label, usd, eur, label == default_text, sort_idx))
    return out


async def _ensure_game(db, *, slug: str, name: str, create_if_missing: bool) -> Game:
    found = (await db.execute(select(Game).where(Game.slug == slug))).scalar_one_or_none()
    if found is not None:
        return found
    if not create_if_missing:
        raise RuntimeError(
            f"Game with slug={slug!r} not found. Pass --create-game-if-missing to auto-create it."
        )
    game = Game(slug=slug, name=name)  # status defaults to ACTIVE
    db.add(game)
    await db.flush()
    return game


async def _upsert_service(
    db, *, game: Game, slug: str, legacy: dict, dry_run: bool, update_existing: bool
) -> tuple[str, int]:
    """Returns (action, options_inserted) where
    action ∈ {created, updated, skipped, would-create, would-update}.
    """
    fields = _build_service_payload(legacy)
    title = fields["title"] or slug

    existing = (
        await db.execute(
            select(Service).options(selectinload(Service.options)).where(Service.slug == slug)
        )
    ).scalar_one_or_none()

    options_data = _build_options(legacy)

    if existing is not None:
        if not update_existing:
            return ("skipped", 0)
        if dry_run:
            return ("would-update", len(options_data))

        # Refresh editable fields. game_id stays put — we don't move a
        # service across games once it's in the wild.
        existing.title = title
        existing.platform = fields["platform"]
        existing.image_desktop_url = fields["image_desktop_url"]
        existing.image_alt = fields["image_alt"]
        existing.description = fields["description"]
        existing.what_you_get = fields["what_you_get"]
        existing.sections = fields["sections"]
        existing.seo_title = fields["seo_title"]
        existing.seo_description = fields["seo_description"]
        # NB: image_mobile_url is NOT overwritten — admins curate it via
        # the panel; importer must not clobber their work on re-runs.

        # Replace options wholesale — orphan-delete cascade cleans the old.
        existing.options.clear()
        await db.flush()
        for label, usd, eur, is_default, sort_order in options_data:
            existing.options.append(
                ServiceOption(
                    label=label,
                    price_usd=usd,
                    price_eur=eur,
                    is_default=is_default,
                    sort_order=sort_order,
                )
            )
        await db.flush()
        return ("updated", len(options_data))

    if dry_run:
        return ("would-create", len(options_data))

    service = Service(
        game_id=game.id,
        slug=slug,
        title=title,
        platform=fields["platform"],
        image_desktop_url=fields["image_desktop_url"],
        image_mobile_url=fields["image_mobile_url"],
        image_alt=fields["image_alt"],
        description=fields["description"],
        what_you_get=fields["what_you_get"],
        sections=fields["sections"],
        seo_title=fields["seo_title"],
        seo_description=fields["seo_description"],
        is_active=True,
        is_featured=False,
        sort_order=0,
    )
    for label, usd, eur, is_default, sort_order in options_data:
        service.options.append(
            ServiceOption(
                label=label,
                price_usd=usd,
                price_eur=eur,
                is_default=is_default,
                sort_order=sort_order,
            )
        )

    db.add(service)
    await db.flush()
    return ("created", len(options_data))


async def import_into(
    db,
    raw: dict,
    *,
    default_game_slug: str,
    game_name: str,
    create_game_if_missing: bool,
    dry_run: bool,
    update_existing: bool = False,
) -> dict:
    """Run the importer against a caller-supplied AsyncSession.

    Returns the summary dict so tests and the CLI both reuse the same path.
    """
    summary = {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "would-create": 0,
        "would-update": 0,
        "failed": 0,
        "options": 0,
    }

    game = await _ensure_game(
        db,
        slug=default_game_slug,
        name=game_name,
        create_if_missing=create_game_if_missing,
    )
    for slug, legacy in raw.items():
        try:
            action, opts = await _upsert_service(
                db,
                game=game,
                slug=slug,
                legacy=legacy,
                dry_run=dry_run,
                update_existing=update_existing,
            )
        except Exception:
            logger.exception("FAIL %s", slug)
            summary["failed"] += 1
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
    update_existing: bool,
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
            update_existing=update_existing,
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
    p.add_argument(
        "--update",
        action="store_true",
        help=(
            "Refresh services that already exist (title, description, "
            "options, prices, image_desktop_url). image_mobile_url and "
            "is_featured / sort_order curated in the admin panel are "
            "preserved."
        ),
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
            update_existing=args.update,
        )
    )
