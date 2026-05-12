import io
import re
from uuid import uuid4

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from app.core.config import settings
from app.core.exceptions import AppError
from app.shared.storage import StoredFile, get_storage

_MIME_TO_EXT = {
    "image/webp": "webp",
    "image/jpeg": "jpg",
    "image/png": "png",
}

_PIL_FORMAT_TO_MIME = {
    "WEBP": "image/webp",
    "JPEG": "image/jpeg",
    "PNG": "image/png",
}

_SLUG_INVALID = re.compile(r"[^a-z0-9]+")
_FOLDER_PATTERN = re.compile(r"^[a-z0-9_-]+$")


class InvalidUploadError(AppError):
    def __init__(self, detail: str) -> None:
        from fastapi import status

        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _slugify_basename(name: str) -> str:
    name = name.lower().rsplit(".", 1)[0]
    slug = _SLUG_INVALID.sub("-", name).strip("-")
    return slug[:60] if slug else "file"


def _validate_image_bytes(content: bytes, declared_mime: str) -> str:
    """Open with PIL to verify magic bytes. Returns canonical content-type."""
    try:
        with Image.open(io.BytesIO(content)) as img:
            img.verify()
            fmt = (img.format or "").upper()
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidUploadError("File is not a valid image") from exc

    actual_mime = _PIL_FORMAT_TO_MIME.get(fmt)
    if actual_mime is None:
        raise InvalidUploadError(f"Image format '{fmt}' is not supported. Use webp, jpeg, or png.")
    if actual_mime != declared_mime:
        raise InvalidUploadError(
            f"Declared content type {declared_mime} does not match actual {actual_mime}"
        )
    return actual_mime


class UploadService:
    def __init__(self) -> None:
        self.storage = get_storage()

    async def upload_image(self, *, file: UploadFile, folder: str) -> StoredFile:
        if not _FOLDER_PATTERN.match(folder):
            raise InvalidUploadError("Invalid folder name")
        if folder not in settings.ALLOWED_UPLOAD_FOLDERS:
            allowed = ", ".join(settings.ALLOWED_UPLOAD_FOLDERS)
            raise InvalidUploadError(f"Folder must be one of: {allowed}")

        declared_mime = (file.content_type or "").lower()
        if declared_mime not in _MIME_TO_EXT:
            raise InvalidUploadError(
                "Unsupported content type. Allowed: image/webp, image/jpeg, image/png"
            )

        content = await file.read()
        if not content:
            raise InvalidUploadError("Uploaded file is empty")
        if len(content) > settings.MAX_UPLOAD_SIZE_BYTES:
            mb = settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
            raise InvalidUploadError(f"File exceeds maximum size of {mb}MB")

        actual_mime = _validate_image_bytes(content, declared_mime)
        ext = _MIME_TO_EXT[actual_mime]

        original = file.filename or "file"
        slug = _slugify_basename(original)
        filename = f"{slug}_{uuid4().hex[:12]}.{ext}"

        return await self.storage.save(
            folder=folder,
            filename=filename,
            content=content,
            content_type=actual_mime,
        )
