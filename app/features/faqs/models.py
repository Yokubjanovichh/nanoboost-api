from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class GameFAQ(Base, TimestampMixin):
    """Per-game FAQ entry — no shared bucket, slug is the only join key.

    `game_slug` is intentionally a plain indexed string, not a foreign key
    to `games.slug`. The games table uses UUID PKs and slugs can be
    renamed; pinning to a string lets the admin pre-create FAQs for a
    new game whose row hasn't been created yet (launch staging), and
    keeps the dependency direction one-way (FAQs reference games, never
    vice versa).
    """

    __tablename__ = "game_faqs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        # Public read path: WHERE game_slug = ? AND is_active = true
        # ORDER BY order_index ASC. Composite covers both filter + sort.
        Index("ix_game_faqs_slug_active_order", "game_slug", "is_active", "order_index"),
    )

    def __repr__(self) -> str:
        return f"<GameFAQ id={self.id} slug={self.game_slug} order={self.order_index}>"
