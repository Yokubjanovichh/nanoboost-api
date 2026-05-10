from uuid import UUID, uuid4

from sqlalchemy import String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class Client(Base, TimestampMixin):
    __tablename__ = "clients"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    discord: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram: Mapped[str | None] = mapped_column(String(255), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Client id={self.id} email={self.email}>"
