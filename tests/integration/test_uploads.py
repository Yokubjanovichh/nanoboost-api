"""Upload endpoint + the /uploads/* serve path (Cache-Control + MIME)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import settings


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color="red").save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_upload_requires_auth(client_with_db):
    res = await client_with_db.post(
        "/api/v1/uploads",
        files={"file": ("x.png", _png_bytes(), "image/png")},
        data={"folder": "misc"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_upload_happy_path(client_with_db, manager_user, auth_headers):
    res = await client_with_db.post(
        "/api/v1/uploads",
        headers=auth_headers(manager_user),
        files={"file": ("hero.png", _png_bytes(), "image/png")},
        data={"folder": "games"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["folder"] == "games"
    assert body["url"].startswith("/uploads/games/")
    # File actually landed on disk.
    path = Path(settings.UPLOADS_DIR) / body["folder"] / body["filename"]
    assert path.exists()


@pytest.mark.asyncio
async def test_upload_rejects_unknown_folder(client_with_db, manager_user, auth_headers):
    res = await client_with_db.post(
        "/api/v1/uploads",
        headers=auth_headers(manager_user),
        files={"file": ("x.png", _png_bytes(), "image/png")},
        data={"folder": "secret"},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_text_file(client_with_db, manager_user, auth_headers):
    res = await client_with_db.post(
        "/api/v1/uploads",
        headers=auth_headers(manager_user),
        files={"file": ("note.txt", b"hello", "text/plain")},
        data={"folder": "misc"},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_served_file_has_cache_and_security_headers(
    client_with_db, manager_user, auth_headers
):
    """End-to-end: upload, then re-fetch and verify the static-mount
    pipeline applies Cache-Control + MIME (PR #11) and security
    headers (PR #14)."""
    upload = await client_with_db.post(
        "/api/v1/uploads",
        headers=auth_headers(manager_user),
        files={"file": ("hero.png", _png_bytes(), "image/png")},
        data={"folder": "games"},
    )
    url = upload.json()["url"]
    served = await client_with_db.get(url)
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert "max-age=31536000" in served.headers["cache-control"]
    assert "immutable" in served.headers["cache-control"]
    # Security headers on the static path too.
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["x-frame-options"] == "DENY"


@pytest.mark.asyncio
async def test_missing_static_file_returns_404_without_cache(client_with_db):
    res = await client_with_db.get("/uploads/games/does-not-exist.png")
    assert res.status_code == 404
    assert "cache-control" not in res.headers
