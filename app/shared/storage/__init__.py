from app.core.config import settings
from app.shared.storage.base import StorageBackend, StoredFile
from app.shared.storage.local import LocalStorageBackend
from app.shared.storage.s3 import S3StorageBackend


def get_storage() -> StorageBackend:
    if settings.STORAGE_BACKEND == "local":
        return LocalStorageBackend(
            root_dir=settings.UPLOADS_DIR,
            url_prefix=settings.UPLOADS_URL_PREFIX,
        )
    if settings.STORAGE_BACKEND == "s3":
        return S3StorageBackend()
    raise ValueError(f"Unknown STORAGE_BACKEND: {settings.STORAGE_BACKEND}")


__all__ = ["StorageBackend", "StoredFile", "get_storage"]
