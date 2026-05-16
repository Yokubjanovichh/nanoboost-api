"""One-off: import the legacy coming-soon games (WoW, Destiny 2, League of
Legends) into the admin DB, including desktop + mobile cover images.

Combines the patterns from `scripts/import_legacy_services.py` (JSON-driven,
idempotent by slug) and `scripts/migrate_legacy_images.py` (HTTP login +
multipart upload). It runs end-to-end via the public API surface — no direct
DB writes — so behaviour matches what the admin panel would do.

Usage:
    python -m scripts.import_legacy_games \\
        --input games-data.json \\
        --assets-dir /c/Users/admin/Desktop/nanoboost/assets/images \\
        --admin-email admin@nanoboost.io \\
        --admin-password <password> \\
        [--base-url ...] [--dry-run] [--update]

Input JSON shape:
    [
      {
        "slug": "wow",
        "name": "World of Warcraft",
        "description": "...",
        "status": "coming_soon",            # active | coming_soon | hidden
        "image_desktop_filename": "games2.webp",
        "image_mobile_filename": "mobgames2.webp",
        "sort_order": 1
      },
      ...
    ]

Idempotency:
  * Game exists (by slug): skipped, unless --update is passed.
  * Image URL already points at /uploads/games/: re-upload skipped.
  * Missing image files log a warning and the script keeps going.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("nanoboost.import_legacy_games")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


REQUIRED_FIELDS = ("slug", "name", "status")
ALLOWED_STATUSES = {"active", "coming_soon", "hidden"}
UPLOADED_PREFIX = "/uploads/games/"


def _load_input(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Input JSON root must be a list of game objects")
    return data


def _validate(entry: dict, index: int) -> None:
    for field in REQUIRED_FIELDS:
        if not entry.get(field):
            raise ValueError(f"Entry #{index}: missing required field {field!r}")
    if entry["status"] not in ALLOWED_STATUSES:
        raise ValueError(
            f"Entry #{index}: status must be one of {sorted(ALLOWED_STATUSES)}, "
            f"got {entry['status']!r}"
        )


async def _login(client: httpx.AsyncClient, base_url: str, email: str, password: str) -> str:
    res = await client.post(
        f"{base_url}/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    res.raise_for_status()
    return res.json()["access_token"]


async def _fetch_games_by_slug(
    client: httpx.AsyncClient, base_url: str, token: str
) -> dict[str, dict]:
    """Single page fetch up to 200 — we only ever have a handful of games."""
    res = await client.get(
        f"{base_url}/api/v1/games",
        params={"page_size": 200},
        headers={"Authorization": f"Bearer {token}"},
    )
    res.raise_for_status()
    return {g["slug"]: g for g in res.json().get("items", [])}


async def _create_game(
    client: httpx.AsyncClient, base_url: str, token: str, payload: dict
) -> dict:
    res = await client.post(
        f"{base_url}/api/v1/games",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    if res.status_code >= 400:
        raise RuntimeError(f"Create game failed ({res.status_code}): {res.text}")
    return res.json()


async def _patch_game(
    client: httpx.AsyncClient, base_url: str, token: str, game_id: str, patch: dict
) -> dict:
    res = await client.patch(
        f"{base_url}/api/v1/games/{game_id}",
        headers={"Authorization": f"Bearer {token}"},
        json=patch,
    )
    if res.status_code >= 400:
        raise RuntimeError(f"Patch game {game_id} failed ({res.status_code}): {res.text}")
    return res.json()


async def _upload_one(
    client: httpx.AsyncClient, base_url: str, token: str, file_path: Path
) -> str:
    """Upload a file to /uploads?folder=games. Returns the public URL."""
    suffix = file_path.suffix.lower()
    mime = {
        ".webp": "image/webp",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(suffix, "application/octet-stream")
    with file_path.open("rb") as fh:
        files = {"file": (file_path.name, fh, mime)}
        data = {"folder": "games"}
        res = await client.post(
            f"{base_url}/api/v1/uploads",
            headers={"Authorization": f"Bearer {token}"},
            files=files,
            data=data,
        )
    if res.status_code >= 400:
        raise RuntimeError(f"Upload failed for {file_path.name}: {res.status_code} {res.text}")
    return res.json()["url"]


async def _maybe_upload_image(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    assets_dir: Path,
    filename: str | None,
    existing_url: str | None,
    slug: str,
    role: str,
    dry_run: bool,
    summary: dict[str, int],
    url_cache: dict[str, str],
) -> str | None:
    """Return the URL to write back, or None if nothing changed.

    Skips work when the current URL is already a /uploads/games/ path —
    that's the idempotency check the TZ asked for.
    """
    if not filename:
        return None

    if existing_url and existing_url.startswith(UPLOADED_PREFIX):
        logger.info("  SKIP   %-12s (%s already uploaded: %s)", slug, role, existing_url)
        summary["image_skipped"] += 1
        return None

    if filename in url_cache:
        cached = url_cache[filename]
        logger.info("  CACHE  %-12s (%s -> %s)", slug, role, cached)
        return cached

    file_path = assets_dir / filename
    if not file_path.exists():
        logger.warning("  MISS   %-12s (%s file missing: %s)", slug, role, file_path)
        summary["missing_file"] += 1
        return None

    if dry_run:
        placeholder = f"<dry-run>{UPLOADED_PREFIX}{filename}"
        url_cache[filename] = placeholder
        logger.info("  DRY    %-12s (%s would upload %s)", slug, role, filename)
        summary["image_uploaded"] += 1
        return placeholder

    url = await _upload_one(client, base_url, token, file_path)
    url_cache[filename] = url
    logger.info("  UP     %-12s (%s -> %s)", slug, role, url)
    summary["image_uploaded"] += 1
    return url


async def _process_entry(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    assets_dir: Path,
    entry: dict,
    existing_by_slug: dict[str, dict],
    dry_run: bool,
    update: bool,
    summary: dict[str, int],
    url_cache: dict[str, str],
) -> None:
    slug = entry["slug"]
    existing = existing_by_slug.get(slug)

    if existing and not update:
        logger.info("SKIP   %-12s (already exists, --update not set)", slug)
        summary["skipped"] += 1
        return

    base_payload = {
        "name": entry["name"],
        "description": entry.get("description"),
        "status": entry["status"],
        "sort_order": int(entry.get("sort_order", 0)),
    }

    if existing is None:
        create_payload = {"slug": slug, **base_payload}
        if dry_run:
            logger.info("CREATE %-12s (dry-run) payload=%s", slug, create_payload)
            game = {"id": f"<dry-run-{slug}>", **create_payload}
            summary["created"] += 1
        else:
            game = await _create_game(client, base_url, token, create_payload)
            logger.info("CREATE %-12s id=%s", slug, game["id"])
            summary["created"] += 1
    else:
        game = existing
        if dry_run:
            logger.info("UPDATE %-12s (dry-run) patch=%s", slug, base_payload)
        else:
            game = await _patch_game(client, base_url, token, game["id"], base_payload)
            logger.info("UPDATE %-12s id=%s", slug, game["id"])
        summary["updated"] += 1

    desktop_url = await _maybe_upload_image(
        client=client,
        base_url=base_url,
        token=token,
        assets_dir=assets_dir,
        filename=entry.get("image_desktop_filename"),
        existing_url=game.get("image_desktop_url"),
        slug=slug,
        role="desktop",
        dry_run=dry_run,
        summary=summary,
        url_cache=url_cache,
    )
    mobile_url = await _maybe_upload_image(
        client=client,
        base_url=base_url,
        token=token,
        assets_dir=assets_dir,
        filename=entry.get("image_mobile_filename"),
        existing_url=game.get("image_mobile_url"),
        slug=slug,
        role="mobile",
        dry_run=dry_run,
        summary=summary,
        url_cache=url_cache,
    )

    image_patch: dict[str, str] = {}
    if desktop_url:
        image_patch["image_desktop_url"] = desktop_url
    if mobile_url:
        image_patch["image_mobile_url"] = mobile_url

    if not image_patch:
        return
    if dry_run:
        logger.info("  PATCH  %-12s (dry-run) %s", slug, image_patch)
        return
    await _patch_game(client, base_url, token, game["id"], image_patch)
    logger.info("  PATCH  %-12s urls written", slug)


async def run(
    *,
    base_url: str,
    input_path: Path,
    assets_dir: Path,
    admin_email: str,
    admin_password: str,
    dry_run: bool,
    update: bool,
) -> int:
    data = _load_input(input_path)
    for idx, entry in enumerate(data):
        _validate(entry, idx)

    summary: dict[str, int] = {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "image_uploaded": 0,
        "image_skipped": 0,
        "missing_file": 0,
        "failed": 0,
    }
    url_cache: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=60.0) as client:
        token = await _login(client, base_url, admin_email, admin_password)
        logger.info("Logged in as %s", admin_email)

        existing_by_slug = await _fetch_games_by_slug(client, base_url, token)
        logger.info("Loaded %d existing games", len(existing_by_slug))

        for entry in data:
            try:
                await _process_entry(
                    client=client,
                    base_url=base_url,
                    token=token,
                    assets_dir=assets_dir,
                    entry=entry,
                    existing_by_slug=existing_by_slug,
                    dry_run=dry_run,
                    update=update,
                    summary=summary,
                    url_cache=url_cache,
                )
            except Exception as exc:
                logger.exception("FAIL   %-12s: %s", entry.get("slug", "?"), exc)
                summary["failed"] += 1

    logger.info("Summary: %s", summary)
    return 1 if summary["failed"] else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Import legacy games + images")
    parser.add_argument("--input", required=True, type=Path, help="Path to games JSON")
    parser.add_argument(
        "--assets-dir",
        required=True,
        type=Path,
        help="Local path to assets/images/ that contains the image filenames",
    )
    parser.add_argument(
        "--base-url",
        default="https://nanoboost-api-production.up.railway.app",
        help="API base URL",
    )
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-password", required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only — no DB writes, no uploads",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Patch existing games instead of skipping them",
    )
    args = parser.parse_args()

    if not args.assets_dir.exists() or not args.assets_dir.is_dir():
        logger.error("assets-dir not found: %s", args.assets_dir)
        sys.exit(1)

    sys.exit(
        asyncio.run(
            run(
                base_url=args.base_url.rstrip("/"),
                input_path=args.input,
                assets_dir=args.assets_dir,
                admin_email=args.admin_email,
                admin_password=args.admin_password,
                dry_run=args.dry_run,
                update=args.update,
            )
        )
    )


if __name__ == "__main__":
    main()
