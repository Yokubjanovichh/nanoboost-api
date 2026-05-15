from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Postgres → JSONB, SQLite (tests) → JSON. Cross-dialect.
JsonPayload = JSON().with_variant(JSONB(astext_type=None), "postgresql")


class PaymentWebhookEvent(Base):
    """Deduplication record for incoming payment-provider webhooks.

    Composite PK (provider, event_id) gives us a natural idempotency key —
    re-deliveries from the same provider with the same event id are ignored.
    """

    __tablename__ = "payment_webhook_events"

    provider: Mapped[str] = mapped_column(String(50), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    order_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JsonPayload, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<PaymentWebhookEvent provider={self.provider} event_id={self.event_id}>"
