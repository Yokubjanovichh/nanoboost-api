import asyncio
from pathlib import Path

from app.shared.storage.base import StorageBackend, StoredFile


class LocalStorageBackend(StorageBackend):
    def __init__(self, *, root_dir: str, url_prefix: str) -> None:
        self.root = Path(root_dir).resolve()
        self.url_prefix = url_prefix.rstrip("/")
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, folder: str, filename: str) -> Path:
        target_dir = (self.root / folder).resolve()
        if not str(target_dir).startswith(str(self.root)):
            raise ValueError("Folder path escapes uploads root")
        target_dir.mkdir(parents=True, exist_ok=True)

        path = (target_dir / filename).resolve()
        if not str(path).startswith(str(target_dir)):
            raise ValueError("Filename path escapes folder")
        return path

    async def save(
        self,
        *,
        folder: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> StoredFile:
        path = self._resolve(folder, filename)

        def _write() -> None:
            path.write_bytes(content)

        await asyncio.to_thread(_write)

        return StoredFile(
            url=f"{self.url_prefix}/{folder}/{filename}",
            filename=filename,
            folder=folder,
            size_bytes=len(content),
            content_type=content_type,
        )

    async def delete(self, *, folder: str, filename: str) -> None:
        path = self._resolve(folder, filename)
        if not path.exists():
            return

        def _unlink() -> None:
            path.unlink(missing_ok=True)

        await asyncio.to_thread(_unlink)
