import logging
from email.message import EmailMessage

import aiosmtplib

from app.shared.notifications.base import NotificationBackend

logger = logging.getLogger("nanoboost.notifications.email")


class SmtpEmailBackend(NotificationBackend):
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        recipient: str,
        timeout: float = 15.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.recipient = recipient
        self.timeout = timeout

    async def send(self, *, subject: str, body: str, **kwargs) -> bool:
        del kwargs
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = self.recipient
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            await aiosmtplib.send(
                msg,
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                start_tls=True,
                timeout=self.timeout,
            )
        except Exception:
            logger.exception("SMTP send failed")
            return False
        return True
