import io
import shutil
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def isolated_uploads_dir(tmp_path, monkeypatch):
    test_dir = tmp_path / "uploads"
    test_dir.mkdir()
    monkeypatch.setattr("app.core.config.settings.UPLOADS_DIR", str(test_dir))
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir, ignore_errors=True)


def _make_webp(size: tuple[int, int] = (10, 10)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=(255, 0, 0)).save(buf, format="WEBP")
    return buf.getvalue()


def _make_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color=(0, 255, 0)).save(buf, format="PNG")
    return buf.getvalue()


async def test_upload_valid_webp(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    content = _make_webp()
    res = await client.post(
        "/api/v1/uploads",
        headers=auth_header(superadmin_token),
        files={"file": ("logo.webp", content, "image/webp")},
        data={"folder": "games"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["folder"] == "games"
    assert body["content_type"] == "image/webp"
    assert body["filename"].endswith(".webp")
    assert body["url"].startswith("/uploads/games/")
    assert body["size_bytes"] == len(content)


async def test_upload_too_large(
    client: AsyncClient, superadmin_token: str, auth_header, monkeypatch
) -> None:
    monkeypatch.setattr("app.core.config.settings.MAX_UPLOAD_SIZE_BYTES", 100)

    content = _make_webp(size=(200, 200))
    assert len(content) > 100

    res = await client.post(
        "/api/v1/uploads",
        headers=auth_header(superadmin_token),
        files={"file": ("big.webp", content, "image/webp")},
        data={"folder": "games"},
    )
    assert res.status_code == 400
    assert "exceeds maximum size" in res.json()["detail"]


async def test_upload_invalid_type(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.post(
        "/api/v1/uploads",
        headers=auth_header(superadmin_token),
        files={"file": ("file.txt", b"hello world", "text/plain")},
        data={"folder": "games"},
    )
    assert res.status_code == 400


async def test_upload_mismatched_magic_bytes(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    res = await client.post(
        "/api/v1/uploads",
        headers=auth_header(superadmin_token),
        files={"file": ("fake.webp", b"not really an image", "image/webp")},
        data={"folder": "games"},
    )
    assert res.status_code == 400


async def test_upload_invalid_folder(
    client: AsyncClient, superadmin_token: str, auth_header
) -> None:
    content = _make_webp()
    res = await client.post(
        "/api/v1/uploads",
        headers=auth_header(superadmin_token),
        files={"file": ("logo.webp", content, "image/webp")},
        data={"folder": "evil"},
    )
    assert res.status_code == 400


async def test_upload_viewer_forbidden(
    client: AsyncClient, viewer_token: str, auth_header
) -> None:
    content = _make_webp()
    res = await client.post(
        "/api/v1/uploads",
        headers=auth_header(viewer_token),
        files={"file": ("logo.webp", content, "image/webp")},
        data={"folder": "games"},
    )
    assert res.status_code == 403


async def test_upload_persists_file_on_disk(
    client: AsyncClient,
    superadmin_token: str,
    auth_header,
    isolated_uploads_dir: Path,
) -> None:
    res = await client.post(
        "/api/v1/uploads",
        headers=auth_header(superadmin_token),
        files={"file": ("photo.png", _make_png(), "image/png")},
        data={"folder": "reviews"},
    )
    assert res.status_code == 201
    filename = res.json()["filename"]
    expected_path = isolated_uploads_dir / "reviews" / filename
    assert expected_path.exists()
    assert expected_path.stat().st_size > 0
