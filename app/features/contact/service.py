from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.clients.models import Client
from app.features.contact.models import ContactSubmission
from app.features.contact.schemas import ContactSubmissionCreate

logger = structlog.get_logger("nanoboost.contact")


class ContactService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def submit(
        self,
        payload: ContactSubmissionCreate,
        *,
        ip_address: str | None,
        user_agent: str | None,
    ) -> ContactSubmission:
        """Insert the submission and best-effort link to an existing Client.

        No auto-create — a contact form lead shouldn't start a Client
        relationship without the order pipeline. Email matches an
        existing Client only when one already exists for that address.
        """
        client_id = await self._link_existing_client(payload.email)

        submission = ContactSubmission(
            preferred_contact=payload.preferred_contact.value,
            handle=payload.handle,
            email=payload.email,
            message=payload.message,
            client_id=client_id,
            ip_address=ip_address,
            user_agent=(user_agent or "")[:500] or None,
        )
        self.db.add(submission)
        await self.db.commit()
        await self.db.refresh(submission)

        # Metadata-only: nothing PII-sensitive (no handle, no message body).
        logger.info(
            "contact_submission_received",
            submission_id=str(submission.id),
            preferred_contact=submission.preferred_contact,
            has_email=bool(submission.email),
            client_linked=bool(submission.client_id),
        )
        return submission

    async def _link_existing_client(self, email: str | None) -> UUID | None:
        if not email:
            return None
        client = (
            await self.db.execute(select(Client).where(Client.email == email))
        ).scalar_one_or_none()
        return client.id if client else None
