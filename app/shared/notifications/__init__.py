import logging

from app.core.config import settings
from app.shared.notifications.base import NoOpBackend, NotificationBackend
from app.shared.notifications.email import SmtpEmailBackend
from app.shared.notifications.orders import OrderNotifier
from app.shared.notifications.telegram import TelegramBackend

logger = logging.getLogger("nanoboost.notifications")


def get_telegram_backend() -> NotificationBackend:
    if not settings.NOTIFICATIONS_ENABLED:
        return NoOpBackend()
    if not settings.TG_ENABLED:
        return NoOpBackend()
    if not settings.TG_BOT_TOKEN or not settings.TG_CHAT_ID:
        logger.warning("Telegram disabled: missing TG_BOT_TOKEN or TG_CHAT_ID")
        return NoOpBackend()
    return TelegramBackend(
        token=settings.TG_BOT_TOKEN,
        chat_id=settings.TG_CHAT_ID,
    )


def get_email_backend() -> NotificationBackend:
    if not settings.NOTIFICATIONS_ENABLED:
        return NoOpBackend()
    if not settings.SMTP_ENABLED:
        return NoOpBackend()
    missing = [
        name
        for name, value in {
            "SMTP_HOST": settings.SMTP_HOST,
            "SMTP_USER": settings.SMTP_USER,
            "SMTP_PASSWORD": settings.SMTP_PASSWORD,
            "NOTIFY_EMAIL": settings.NOTIFY_EMAIL,
        }.items()
        if not value
    ]
    if missing:
        logger.warning("Email disabled: missing %s", ", ".join(missing))
        return NoOpBackend()
    return SmtpEmailBackend(
        host=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        username=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD,
        sender=settings.SMTP_FROM,
        recipient=settings.NOTIFY_EMAIL,
    )


def get_order_notifier() -> OrderNotifier:
    return OrderNotifier(
        telegram=get_telegram_backend(),
        email=get_email_backend(),
    )


__all__ = [
    "NoOpBackend",
    "NotificationBackend",
    "OrderNotifier",
    "SmtpEmailBackend",
    "TelegramBackend",
    "get_email_backend",
    "get_order_notifier",
    "get_telegram_backend",
]
