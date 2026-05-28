from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import Platform
from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.features.games.models import Game

# Cross-dialect JSON: JSONB on Postgres, JSON elsewhere (e.g. SQLite tests).
JsonList = JSON().with_variant(JSONB(astext_type=None), "postgresql")


class Service(Base, TimestampMixin):
    __tablename__ = "services"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("games.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    platform: Mapped[Platform] = mapped_column(
        SAEnum(
            Platform,
            name="service_platform",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    image_desktop_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_mobile_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_alt: Mapped[str | None] = mapped_column(String(300), nullable=True)

    description: Mapped[list] = mapped_column(JsonList, nullable=False, default=list)
    what_you_get: Mapped[list] = mapped_column(JsonList, nullable=False, default=list)
    sections: Mapped[list] = mapped_column(JsonList, nullable=False, default=list)

    seo_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    seo_description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    options: Mapped[list["ServiceOption"]] = relationship(
        "ServiceOption",
        back_populates="service",
        cascade="all, delete-orphan",
        order_by="ServiceOption.sort_order",
        lazy="raise",
    )
    game: Mapped[Game] = relationship(
        "Game",
        foreign_keys=[game_id],
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<Service id={self.id} slug={self.slug} platform={self.platform}>"


class ServiceOption(Base, TimestampMixin):
    __tablename__ = "service_options"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    service_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("services.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    price_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Per-option discount. Mutually exclusive: either percent OR a pair of
    # USD/EUR amounts. NULL on all three = no discount. Invariants are
    # enforced at the Pydantic schema layer (see ServiceOptionBase /
    # ServiceOptionUpdate validators) — keeping the DB liberal avoids
    # making historical rows un-readable when a future tweak relaxes the
    # rule. Order-level discounts (e.g. USDT 5%) stack on top of any
    # item-level discount because the order subtotal is computed from the
    # already-discounted unit price.
    # NUMERIC(7,3) lets the admin target sub-percent rates (12.5%, 7.499%).
    # Integers stored as 10 (legacy) read back as Decimal("10.000") — the
    # downstream Decimal math produces identical totals after quantize.
    discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 3), nullable=True)
    discount_amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    discount_amount_eur: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    service: Mapped[Service] = relationship("Service", back_populates="options")

    def __repr__(self) -> str:
        return f"<ServiceOption id={self.id} label={self.label}>"
