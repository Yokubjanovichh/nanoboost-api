import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.constants import DisplayCurrency, OrderStatus, PaymentMethod

# E.164-friendly: optional leading +, then 7-50 chars of digits/spaces/dashes.
# Wider than strict E.164 because we accept user-typed formats and normalize
# server-side to `+<digits>` before storing on the client record.
_WHATSAPP_RE = re.compile(r"^\+?[0-9\s\-]{7,50}$")


class PublicOrderItemCreate(BaseModel):
    # Public surface — we identify the catalogue row by its URL-friendly slug,
    # never by UUID. The slug is what the FE already routes on and what the
    # admin curates; leaking primary keys would be both ugly and a footgun if
    # we ever change the PK strategy.
    service_slug: str = Field(..., min_length=1, max_length=128)
    option_id: Annotated[UUID, Field(description="Selected service option")]
    qty: int = Field(..., ge=1, le=100)

    # Reject unknown fields outright. Previously `extra='ignore'` (Pydantic
    # default) meant the FE could send `qty` when we expected `quantity` and
    # Pydantic silently dropped it — every order ended up with the schema
    # default. A 422 here is the right signal: the contract is wrong, not
    # the data.
    model_config = ConfigDict(extra="forbid")


class PublicOrderCreate(BaseModel):
    email: EmailStr
    discord: str | None = Field(default=None, max_length=255)
    telegram: str | None = Field(default=None, max_length=255)
    whatsapp: str | None = Field(default=None, max_length=50)
    payment_method: PaymentMethod
    display_currency: DisplayCurrency = DisplayCurrency.USD
    comment: str | None = Field(default=None, max_length=2000)
    items: list[PublicOrderItemCreate] = Field(min_length=1)

    @field_validator("whatsapp", mode="before")
    @classmethod
    def _normalize_whatsapp(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            return None
        if not _WHATSAPP_RE.match(s):
            raise ValueError(
                "whatsapp must be 7-50 chars: optional leading +, digits, spaces, dashes"
            )
        # Normalize to +<digits>: drop spaces/dashes, keep leading + if present.
        plus = "+" if s.startswith("+") else ""
        digits = re.sub(r"[^0-9]", "", s)
        return f"{plus}{digits}"


class PublicOrderResponse(BaseModel):
    order_number: str
    status: OrderStatus
    # `final_total_usd` is the canonical total — always present, non-null.
    # `final_total_eur` is the EUR snapshot at order creation (NULL on
    # rows created before migration 0011). `discount_amount_usd` echoes
    # the server-computed discount so the FE can render breakdown without
    # re-computing it.
    final_total_usd: float
    final_total_eur: float | None = None
    discount_amount_usd: float | None = None
    display_currency: DisplayCurrency
    created_at: datetime
    # Populated when the chosen payment_method has a hosted-checkout provider
    # registered (e.g. card_ecomtrade24). PayPal/USDT keep this as None.
    checkout_url: str | None = None


class PaymentClaimResponse(BaseModel):
    """Returned by POST /public/orders/{number}/claim-payment.

    Idempotent: if the claim was already filed, the original
    `payment_claimed_at` is returned and no new Telegram alert is sent.
    Status stays `pending` — only the admin's manual verification
    advances it to `paid`.
    """

    order_number: str
    status: OrderStatus
    payment_claimed_at: datetime | None = None


class PublicOrderStatusResponse(BaseModel):
    """Polled by the public payment-success page. Intentionally PII-free —
    anyone with the order_number can read this, same trust level as a
    Stripe/PayPal session reference.
    """

    order_number: str
    status: OrderStatus
    paid_at: datetime | None = None
    final_total_usd: float
    final_total_eur: float | None = None
    display_currency: DisplayCurrency
    # Latest of payment_status_updated_at / updated_at — lets the polling
    # client detect "no change since last poll" without diffing the whole
    # body. Always present.
    last_updated_at: datetime
