from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer


class ClientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    discord: str | None
    telegram: str | None
    whatsapp: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ClientStats(BaseModel):
    total_orders: int = 0
    total_spent_usd: Decimal = Decimal("0")
    first_order_at: datetime | None = None
    last_order_at: datetime | None = None

    @field_serializer("total_spent_usd")
    def _serialize_decimal(self, value: Decimal) -> float:
        return float(value)


class ClientWithStats(ClientRead):
    stats: ClientStats


class ClientUpdate(BaseModel):
    discord: str | None = Field(default=None, max_length=255)
    telegram: str | None = Field(default=None, max_length=255)
    whatsapp: str | None = Field(default=None, max_length=50)
    notes: str | None = None


class ClientSummary(BaseModel):
    """Compact client representation embedded in order responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    discord: str | None
    telegram: str | None
