from app.shared.storage.base import StorageBackend, StoredFile


class S3StorageBackend(StorageBackend):
    """V2 placeholder. Will be implemented when migrating to AWS S3 / Cloudinary."""

    async def save(
        self,
        *,
        folder: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> StoredFile:
        raise NotImplementedError("S3 storage backend is planned for V2")

    async def delete(self, *, folder: str, filename: str) -> None:
        raise NotImplementedError("S3 storage backend is planned for V2")
