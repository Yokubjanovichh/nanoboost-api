import logging

import httpx

from app.shared.notifications.base import NotificationBackend

logger = logging.getLogger("nanoboost.notifications.telegram")


class TelegramBackend(NotificationBackend):
    def __init__(self, *, token: str, chat_id: str, timeout: float = 10.0) -> None:
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout

    @property
    def url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}/sendMessage"

    async def send(self, *, subject: str = "", body: str, **kwargs) -> bool:
        del subject, kwargs
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.url,
                    json={
                        "chat_id": self.chat_id,
                        "text": body,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True,
                    },
                )
                if response.status_code != 200:
                    logger.warning(
                        "Telegram non-200: %s %s",
                        response.status_code,
                        response.text[:200],
                    )
                    return False
        except Exception:
            logger.exception("Telegram send failed")
            return False
        return True
