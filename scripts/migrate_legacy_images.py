"""One-off: re-upload legacy /assets/images/* into /uploads/services/ and
rewrite Service.image_desktop_url to the new URL.

Why: the importer (Phase 1.5) kept the original frontend asset paths so the
public vanilla site kept working. Now that the admin panel and any future
frontend live on different origins, every reader needs an absolute URL that
the backend itself serves. This script lifts the assets into the backend's
upload folder and rewrites the column.

Usage (locally, with Railway-injected DATABASE_URL):
    railway run python -m scripts.migrate_legacy_images \\
        --assets-dir /c/Users/admin/Desktop/nanoboost/assets/images \\
        --admin-email admin@nanoboost.io \\
        --admin-password <password> \\
        [--dry-run]

The script logs in via /api/v1/auth/login, uploads each file via
/api/v1/uploads (multipart), and updates the matching Service rows. Idempotent:
URLs already pointing at /uploads/ are skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.features.services.models import Service

logger = logging.getLogger("nanoboost.migrate_images")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _filename_from_legacy(url: str) -> str | None:
    """`/assets/images/services2.webp` -> `services2.webp`. None if not legacy."""
    if not url or not url.startswith("/assets/images/"):
        return None
    return url.rsplit("/", 1)[-1]


async def _login(client: httpx.AsyncClient, base_url: str, email: str, password: str) -> str:
    res = await client.post(
        f"{base_url}/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    res.raise_for_status()
    return res.json()["access_token"]


async def _upload_one(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    file_path: Path,
) -> str:
    """Returns the uploaded file URL (e.g. /uploads/services/foo.webp)."""
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
        raise RuntimeError(f"Upload failed for {file_path.name}: {res.status_code} {res.text}")
    return res.json()["url"]


async def run(
    *,
    base_url: str,
    assets_dir: Path,
    admin_email: str,
    admin_password: str,
    dry_run: bool,
) -> None:
    summary = {"uploaded": 0, "rewrote": 0, "skipped": 0, "missing_file": 0}
    url_cache: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=60.0) as http:
        token = await _login(http, base_url, admin_email, admin_password)
        logger.info("Logged in as %s", admin_email)

        async with AsyncSessionLocal() as db:
            services = (await db.execute(select(Service))).scalars().all()
            logger.info("Loaded %d services", len(services))

            for svc in services:
                filename = _filename_from_legacy(svc.image_desktop_url or "")
                if filename is None:
                    summary["skipped"] += 1
                    continue

                if filename in url_cache:
                    new_url = url_cache[filename]
                    logger.info("[cache] %s -> %s", svc.slug, new_url)
                else:
                    file_path = assets_dir / filename
                    if not file_path.exists():
                        logger.warning("MISSING %s: %s", svc.slug, file_path)
                        summary["missing_file"] += 1
                        continue
                    if dry_run:
                        logger.info("[dry-run] would upload %s for %s", filename, svc.slug)
                        url_cache[filename] = f"<dry-run>/{filename}"
                        summary["uploaded"] += 1
                        new_url = url_cache[filename]
                    else:
                        new_url = await _upload_one(http, base_url, token, file_path)
                        url_cache[filename] = new_url
                        summary["uploaded"] += 1
                        logger.info("uploaded %s -> %s", filename, new_url)

                if dry_run:
                    logger.info("[dry-run] would rewrite %s.image_desktop_url", svc.slug)
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
    parser = argparse.ArgumentParser(description="Migrate /assets/images/* into /uploads/services/")
    parser.add_argument(
        "--base-url",
        default="https://nanoboost-api-production.up.railway.app",
        help="API base URL",
    )
    parser.add_argument(
        "--assets-dir",
        type=Path,
        required=True,
        help="Local path to nanoboost/assets/images/",
    )
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-password", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.assets_dir.exists() or not args.assets_dir.is_dir():
        logger.error("assets-dir not found: %s", args.assets_dir)
        sys.exit(1)

    asyncio.run(
        run(
            base_url=args.base_url,
            assets_dir=args.assets_dir,
            admin_email=args.admin_email,
            admin_password=args.admin_password,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
