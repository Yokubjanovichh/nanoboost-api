from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# INET on Postgres gives cheap subnet queries; cross-dialect String
# elsewhere so SQLite tests stay green.
_IpAddressColumn = String(45).with_variant(INET(), "postgresql")


class ContactSubmission(Base):
    __tablename__ = "contact_submissions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    preferred_contact: Mapped[str] = mapped_column(String(20), nullable=False)
    handle: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
    )
    ip_address: Mapped[str | None] = mapped_column(_IpAddressColumn, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        return f"<ContactSubmission id={self.id} via={self.preferred_contact}>"
