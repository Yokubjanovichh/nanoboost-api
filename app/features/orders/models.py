from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import DisplayCurrency, OrderStatus, PaymentMethod
from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.features.clients.models import Client

JsonDict = JSON().with_variant(JSONB(astext_type=None), "postgresql")


def _enum_values(cls):
    return [e.value for e in cls]


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    order_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    client_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("clients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(
            OrderStatus,
            name="order_status",
            values_callable=lambda x: _enum_values(x),
        ),
        nullable=False,
        default=OrderStatus.PENDING,
        index=True,
    )
    payment_method: Mapped[PaymentMethod] = mapped_column(
        SAEnum(
            PaymentMethod,
            name="payment_method",
            values_callable=lambda x: _enum_values(x),
        ),
        nullable=False,
    )
    display_currency: Mapped[DisplayCurrency] = mapped_column(
        SAEnum(
            DisplayCurrency,
            name="display_currency",
            values_callable=lambda x: _enum_values(x),
        ),
        nullable=False,
        default=DisplayCurrency.USD,
    )

    subtotal_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    discount_amount_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0")
    )
    discount_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    final_total_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # EUR snapshot at order creation — frozen alongside the per-item EUR
    # prices on OrderItem. Nullable for backward compat with rows created
    # before migration 0011; new orders always populate it.
    final_total_eur: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    awaiting_booster_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    booster_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_to_client_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Customer-driven signal for manual-payment flows (PayPal / USDT TRC20):
    # set when the buyer clicks "I have paid" on the success page, before
    # the admin verifies and flips status → PAID. Stays NULL for
    # hosted-checkout providers, which set `paid_at` directly from webhook.
    payment_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Payment provider integration (provider-agnostic — set by gateway adapter)
    payment_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_checkout_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payment_status_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItem.created_at",
        lazy="raise",
    )
    client: Mapped[Client] = relationship(
        "Client",
        foreign_keys=[client_id],
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<Order order_number={self.order_number} status={self.status}>"


class OrderItem(Base, TimestampMixin):
    __tablename__ = "order_items"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Loose foreign-key reference. Service may be soft-deleted later;
    # ON DELETE SET NULL on hard delete keeps the order intact.
    service_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("services.id", ondelete="SET NULL"),
        nullable=True,
    )
    option_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("service_options.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Frozen point-in-time copy of the chosen service.
    # Shape: {slug, title, image_url, platform, game_slug}
    service_snapshot: Mapped[dict] = mapped_column(JsonDict, nullable=False, default=dict)

    option_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unit_price_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total_price_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total_price_eur: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0")
    )

    order: Mapped[Order] = relationship("Order", back_populates="items")

    def __repr__(self) -> str:
        title = (self.service_snapshot or {}).get("title") if self.service_snapshot else None
        return f"<OrderItem id={self.id} title={title}>"
