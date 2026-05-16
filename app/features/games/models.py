from uuid import UUID, uuid4

from sqlalchemy import Boolean, Integer, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import GameStatus
from app.db.base import Base
from app.db.mixins import TimestampMixin


class Game(Base, TimestampMixin):
    __tablename__ = "games"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_desktop_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_mobile_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[GameStatus] = mapped_column(
        SAEnum(
            GameStatus,
            name="game_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=GameStatus.ACTIVE,
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return f"<Game id={self.id} slug={self.slug} status={self.status}>"
