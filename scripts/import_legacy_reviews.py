"""One-off: import the 10 hardcoded testimonials from nanoboost/index.html
into the `reviews` table.

The frontend currently ships testimonials inline. We're moving them into
the admin DB so they can be edited / sorted / featured without a deploy,
and so /public/reviews can serve them with the matching service label.

Usage:
    python -m scripts.import_legacy_reviews --input reviews-data.json
    python -m scripts.import_legacy_reviews --input reviews-data.json --dry-run

Input JSON shape:
    [
      {
        "author_name": "ShadowVortex",
        "rating": 5,
        "text": "Fast delivery ...",
        "service_slug": "gta-cash-cars-ps",     # preferred — direct FK lookup
        "service_label": "GTA Cash + Cars (PS)", # optional, only logged
        "is_featured": false,
        "sort_order": 0
      },
      ...
    ]

Idempotent: dedupe on (author_name, rating, text). Re-running is a no-op
for rows already present, and only creates the missing ones.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.features.reviews.models import Review
from app.features.services.models import Service

logger = logging.getLogger("nanoboost.import_legacy_reviews")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


REQUIRED_FIELDS = ("author_name", "rating", "text")


def _load_input(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Input JSON root must be a list of review objects")
    return data


def _validate(entry: dict, index: int) -> None:
    for field in REQUIRED_FIELDS:
        if field not in entry:
            raise ValueError(f"Entry #{index}: missing required field {field!r}")
    rating = entry["rating"]
    if not isinstance(rating, int) or not 1 <= rating <= 5:
        raise ValueError(f"Entry #{index}: rating must be int 1..5, got {rating!r}")
    text = entry["text"]
    if not isinstance(text, str) or len(text) < 10:
        raise ValueError(f"Entry #{index}: text must be a string of length >= 10")


async def _resolve_service_map(db, slugs: set[str]) -> dict[str, Service]:
    if not slugs:
        return {}
    rows = (
        await db.execute(select(Service).where(Service.slug.in_(slugs)))
    ).scalars().all()
    return {svc.slug: svc for svc in rows}


async def _existing_signatures(db) -> set[tuple[str, int, str]]:
    rows = (
        await db.execute(
            select(Review.author_name, Review.rating, Review.text).where(
                Review.is_deleted.is_(False)
            )
        )
    ).all()
    return {(r[0], r[1], r[2]) for r in rows}


async def run(input_path: Path, *, dry_run: bool) -> int:
    data = _load_input(input_path)
    for idx, entry in enumerate(data):
        _validate(entry, idx)

    wanted_slugs = {
        e["service_slug"].strip()
        for e in data
        if isinstance(e.get("service_slug"), str) and e["service_slug"].strip()
    }

    async with AsyncSessionLocal() as db:
        services = await _resolve_service_map(db, wanted_slugs)
        missing = wanted_slugs - services.keys()
        if missing:
            logger.warning(
                "Service slug(s) not found, those reviews will have service_id=None: %s",
                sorted(missing),
            )

        existing = await _existing_signatures(db)

        created = 0
        skipped = 0
        for idx, entry in enumerate(data):
            sig = (entry["author_name"], entry["rating"], entry["text"])
            if sig in existing:
                logger.info(
                    "SKIP  #%02d %-20s rating=%d (duplicate)",
                    idx,
                    entry["author_name"],
                    entry["rating"],
                )
                skipped += 1
                continue

            slug = entry.get("service_slug")
            svc = services.get(slug.strip()) if isinstance(slug, str) else None
            label = entry.get("service_label") or (svc.title if svc else "—")

            review = Review(
                author_name=entry["author_name"],
                rating=entry["rating"],
                text=entry["text"],
                service_id=svc.id if svc else None,
                is_featured=bool(entry.get("is_featured", False)),
                sort_order=int(entry.get("sort_order", idx)),
                is_active=True,
            )
            db.add(review)
            existing.add(sig)
            created += 1
            logger.info(
                "ADD   #%02d %-20s rating=%d  service=%s",
                idx,
                entry["author_name"],
                entry["rating"],
                label,
            )

        if dry_run:
            await db.rollback()
            logger.info(
                "DRY-RUN complete. Would create=%d, skipped=%d, total=%d",
                created,
                skipped,
                len(data),
            )
        else:
            await db.commit()
            logger.info(
                "Done. Created=%d, skipped=%d, total=%d",
                created,
                skipped,
                len(data),
            )

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Path to reviews JSON")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse + log without writing to the DB",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.input, dry_run=args.dry_run)))


if __name__ == "__main__":
    main()
