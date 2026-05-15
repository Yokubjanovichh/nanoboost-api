from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.core.constants import DisplayCurrency, OrderStatus, PaymentMethod


class PublicOrderItemCreate(BaseModel):
    service_id: UUID
    option_id: Annotated[UUID, Field(description="Selected service option")]
    quantity: int = Field(default=1, ge=1, le=100)


class PublicOrderCreate(BaseModel):
    email: EmailStr
    discord: str | None = Field(default=None, max_length=255)
    telegram: str | None = Field(default=None, max_length=255)
    whatsapp: str | None = Field(default=None, max_length=50)
    payment_method: PaymentMethod
    display_currency: DisplayCurrency = DisplayCurrency.USD
    comment: str | None = Field(default=None, max_length=2000)
    items: list[PublicOrderItemCreate] = Field(min_length=1)


class PublicOrderResponse(BaseModel):
    order_number: str
    status: OrderStatus
    final_total_usd: float
    display_currency: DisplayCurrency
    created_at: datetime
    # Populated when the chosen payment_method has a hosted-checkout provider
    # registered (e.g. card_ecomtrade24). PayPal/USDT keep this as None.
    checkout_url: str | None = None
