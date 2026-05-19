"""Contact-form Telegram notifier.

Fire-and-forget — the endpoint logs the submission to the DB regardless
of whether Telegram delivery succeeds, so a transient Telegram outage
never costs us a customer lead. Telegram errors are swallowed and
logged (matches the OrderNotifier pattern).

Uses the existing TelegramBackend (Markdown parse_mode) rather than
adding a second backend with HTML — keeps the broker integration in
one place. All user-controlled fields run through `_md_safe` so a
crafted handle / message can't inject Telegram formatting.
"""

from __future__ import annotations

import re

import structlog

from app.features.contact.models import ContactSubmission
from app.shared.notifications.base import NotificationBackend

logger = structlog.get_logger("nanoboost.notifications.contact")

# Telegram MarkdownV1-safe: strip the chars that could be interpreted
# as formatting. Same approach as OrderNotifier's _md_safe — short list,
# easy to audit, no rendering tricks.
_MD_SAFE_RE = re.compile(r"[_*`\[\]]")


def _md(value: str | None) -> str:
    if not value:
        return "-"
    return _MD_SAFE_RE.sub("", value)


class ContactNotifier:
    def __init__(self, telegram: NotificationBackend) -> None:
        self._telegram = telegram

    def format(self, sub: ContactSubmission) -> str:
        # Truncate the message body — Telegram has its own limits and
        # we don't want a 2,000-char log line in the broker.
        body_preview = (sub.message or "")[:1500]
        if len(sub.message or "") > 1500:
            body_preview += " […truncated]"

        lines = [
            "📨 *New contact form submission*",
            "",
            f"*Preferred contact:* {_md(sub.preferred_contact)}",
            f"*Handle:* `{_md(sub.handle)}`",
            f"*Email:* {_md(sub.email)}",
            f"*Linked customer:* {sub.client_id or 'No'}",
            "",
            "*Message:*",
            _md(body_preview),
            "",
            f"_ID: {sub.id}_",
        ]
        return "\n".join(lines)

    async def send(self, submission: ContactSubmission) -> None:
        body = self.format(submission)
        try:
            delivered = await self._telegram.send(body=body)
        except Exception:
            # Fire-and-forget: a notification failure must never bubble
            # up into the BackgroundTasks runner — the submission is
            # already durable in the DB.
            logger.exception("contact_notification_crashed", submission_id=str(submission.id))
            return
        if not delivered:
            # Backend already logged the detail; we log the event for
            # contact-specific dashboards.
            logger.warning("contact_notification_failed", submission_id=str(submission.id))
