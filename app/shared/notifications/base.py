from abc import ABC, abstractmethod


class NotificationBackend(ABC):
    """Best-effort notification channel.

    Implementations MUST NOT raise — they catch their own errors,
    log, and return False. Failure of one channel must not affect
    business transactions or other channels.
    """

    @abstractmethod
    async def send(self, *, subject: str, body: str, **kwargs) -> bool: ...


class NoOpBackend(NotificationBackend):
    """Used when notifications are disabled (dev, tests, missing config)."""

    async def send(self, *, subject: str = "", body: str = "", **kwargs) -> bool:
        return True
