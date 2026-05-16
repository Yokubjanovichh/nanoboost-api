"""One-off: re-upload service images to the freshly mounted /app/uploads
volume and overwrite Service.image_desktop_url with the new URLs.

Reads the legacy services-data.json (slug -> {imageSrc: "../assets/images/foo.webp"})
to recover the original filename per slug, finds the file on disk, uploads it
via POST /api/v1/uploads, and updates the DB row.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.features.services.models import Service

logger = logging.getLogger("nanoboost.reupload_images")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _filename_from_legacy(image_src: str | None) -> str | None:
    if not image_src:
        return None
    return image_src.rsplit("/", 1)[-1]


async def _login(client: httpx.AsyncClient, base_url: str, email: str, password: str) -> str:
    res = await client.post(
        f"{base_url}/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    res.raise_for_status()
    return res.json()["access_token"]


async def _upload_one(client: httpx.AsyncClient, base_url: str, token: str, file_path: Path) -> str:
    mime = "image/webp" if file_path.suffix.lower() == ".webp" else "application/octet-stream"
    with file_path.open("rb") as fh:
        files = {"file": (file_path.name, fh, mime)}
        data = {"folder": "services"}
        res = await client.post(
            f"{base_url}/api/v1/uploads",
            headers={"Authorization": f"Bearer {token}"},
            files=files,
            data=data,
        )
    if res.status_code >= 400:
        raise RuntimeError(f"Upload {file_path.name} failed: {res.status_code} {res.text}")
    return res.json()["url"]


async def run(
    *,
    base_url: str,
    assets_dir: Path,
    legacy_json: Path,
    admin_email: str,
    admin_password: str,
    dry_run: bool,
) -> None:
    legacy = json.loads(legacy_json.read_text(encoding="utf-8"))
    summary = {"uploaded": 0, "rewrote": 0, "skipped": 0, "missing_file": 0, "no_mapping": 0}
    url_cache: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=60.0) as http:
        token = await _login(http, base_url, admin_email, admin_password)
        logger.info("Logged in as %s", admin_email)

        async with AsyncSessionLocal() as db:
            services = (await db.execute(select(Service))).scalars().all()
            logger.info("Loaded %d services from DB", len(services))

            for svc in services:
                meta = legacy.get(svc.slug)
                if not meta:
                    logger.warning("no legacy mapping for %s", svc.slug)
                    summary["no_mapping"] += 1
                    continue

                filename = _filename_from_legacy(meta.get("imageSrc"))
                if not filename:
                    summary["no_mapping"] += 1
                    continue

                file_path = assets_dir / filename
                if not file_path.exists():
                    logger.warning("MISSING %s -> %s", svc.slug, file_path)
                    summary["missing_file"] += 1
                    continue

                if filename in url_cache:
                    new_url = url_cache[filename]
                    logger.info("[cache] %s -> %s", svc.slug, new_url)
                else:
                    if dry_run:
                        new_url = f"<dry-run>/{filename}"
                    else:
                        new_url = await _upload_one(http, base_url, token, file_path)
                        logger.info("uploaded %s -> %s", filename, new_url)
                    url_cache[filename] = new_url
                    summary["uploaded"] += 1

                if dry_run:
                    logger.info(
                        "[dry-run] would rewrite %s.image_desktop_url=%s", svc.slug, new_url
                    )
                else:
                    svc.image_desktop_url = new_url
                summary["rewrote"] += 1

            if dry_run:
                await db.rollback()
                logger.info("Dry run — rollback complete")
            else:
                await db.commit()
                logger.info("Commit complete")

    logger.info("Summary: %s", summary)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://nanoboost-api-production.up.railway.app")
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--legacy-json", type=Path, required=True)
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-password", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.assets_dir.is_dir():
        logger.error("assets-dir not found: %s", args.assets_dir)
        sys.exit(1)
    if not args.legacy_json.exists():
        logger.error("legacy-json not found: %s", args.legacy_json)
        sys.exit(1)

    asyncio.run(
        run(
            base_url=args.base_url,
            assets_dir=args.assets_dir,
            legacy_json=args.legacy_json,
            admin_email=args.admin_email,
            admin_password=args.admin_password,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
