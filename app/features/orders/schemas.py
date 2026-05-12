from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_serializer,
)

from app.core.constants import DisplayCurrency, OrderStatus, PaymentMethod
from app.features.clients.schemas import ClientSummary

PriceField = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]


class ServiceSnapshot(BaseModel):
    """Frozen copy of the chosen service at order time.

    `slug` and `title` are required; the others are best-effort and may be
    None for legacy rows backfilled by the 0005 migration.
    """

    slug: str
    title: str
    image_url: str | None = None
    platform: str | None = None
    game_slug: str | None = None


# --- OrderItem schemas -------------------------------------------------------


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    service_id: UUID | None
    option_id: UUID | None
    service_snapshot: ServiceSnapshot
    option_label: str | None
    quantity: int
    unit_price_usd: Decimal
    unit_price_eur: Decimal
    total_price_usd: Decimal
    total_price_eur: Decimal
    created_at: datetime

    @field_serializer(
        "unit_price_usd",
        "unit_price_eur",
        "total_price_usd",
        "total_price_eur",
    )
    def _serialize_decimal(self, value: Decimal) -> float:
        return float(value)


class OrderItemCreate(BaseModel):
    """Used by the internal create flow and the Phase 5 public endpoint.

    Either `service_id` (preferred — backend builds the snapshot from
    the live `services` row) or `service_snapshot` (legacy / migrations)
    must be supplied. Validation is performed in the service layer.
    """

    service_id: UUID | None = None
    option_id: UUID | None = None
    service_snapshot: ServiceSnapshot | None = None
    option_label: str | None = Field(default=None, max_length=200)
    quantity: int = Field(ge=1, default=1)
    unit_price_usd: PriceField
    unit_price_eur: PriceField


# --- Order schemas -----------------------------------------------------------


class OrderInternalCreate(BaseModel):
    """Internal payload — used by Phase 5 public endpoint and tests."""

    email: EmailStr
    discord: str | None = Field(default=None, max_length=255)
    telegram: str | None = Field(default=None, max_length=255)
    whatsapp: str | None = Field(default=None, max_length=50)
    payment_method: PaymentMethod
    display_currency: DisplayCurrency = DisplayCurrency.USD
    discount_percent: int = Field(ge=0, le=100, default=0)
    comment: str | None = None
    items: list[OrderItemCreate] = Field(min_length=1)


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_number: str
    client_id: UUID
    client: ClientSummary
    status: OrderStatus
    payment_method: PaymentMethod
    display_currency: DisplayCurrency
    subtotal_usd: Decimal
    discount_amount_usd: Decimal
    discount_percent: int
    final_total_usd: Decimal
    comment: str | None
    admin_notes: str | None
    paid_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    refunded_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items_count: int = 0

    @field_serializer("subtotal_usd", "discount_amount_usd", "final_total_usd")
    def _serialize_decimal(self, value: Decimal) -> float:
        return float(value)


class OrderDetailRead(OrderRead):
    items: list[OrderItemRead]


class OrderUpdate(BaseModel):
    comment: str | None = None
    admin_notes: str | None = None


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


# --- Stats -------------------------------------------------------------------


class StatusBreakdown(BaseModel):
    status: OrderStatus
    count: int


class OrderStats(BaseModel):
    total_orders: int
    total_revenue_usd: Decimal
    orders_today: int
    revenue_today_usd: Decimal
    avg_order_value_usd: Decimal
    by_status: list[StatusBreakdown]

    @field_serializer("total_revenue_usd", "revenue_today_usd", "avg_order_value_usd")
    def _serialize_decimal(self, value: Decimal) -> float:
        return float(value)
