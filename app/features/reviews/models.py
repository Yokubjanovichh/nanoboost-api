from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.features.services.models import Service


class Review(Base, TimestampMixin):
    __tablename__ = "reviews"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    author_name: Mapped[str] = mapped_column(String(100), nullable=False)
    service_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("services.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    service: Mapped[Service | None] = relationship(
        "Service",
        foreign_keys=[service_id],
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<Review id={self.id} author={self.author_name} rating={self.rating}>"
