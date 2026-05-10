from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class StoredFile:
    url: str
    filename: str
    folder: str
    size_bytes: int
    content_type: str


class StorageBackend(ABC):
    @abstractmethod
    async def save(
        self,
        *,
        folder: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> StoredFile:
        ...

    @abstractmethod
    async def delete(self, *, folder: str, filename: str) -> None:
        ...
