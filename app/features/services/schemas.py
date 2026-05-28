from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.core.constants import Platform

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
PriceField = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]


def calculate_discounted_price(option: object, currency: str) -> Decimal:
    """Apply the option's discount to the price in the requested currency.

    Accepts any object exposing the discount and price attributes — ORM
    rows, Pydantic schemas, dataclasses — so the same helper services
    response serialization, order item pricing and admin previews.

    Rules:
      - No discount fields set    → original price (rounded to cents).
      - discount_percent          → price * (100 - percent) / 100.
      - discount_amount_<currency> → max(price - amount, 0).
    Percent wins if both somehow co-exist on a row (defensive — the
    schema layer rejects that combination, but DB rows are liberal).
    """
    currency = currency.upper()
    if currency not in {"USD", "EUR"}:
        raise ValueError(f"Unsupported currency: {currency!r}")

    base = option.price_usd if currency == "USD" else option.price_eur
    base = Decimal(base) if not isinstance(base, Decimal) else base

    percent = getattr(option, "discount_percent", None)
    if percent:
        factor = (Decimal(100) - Decimal(percent)) / Decimal(100)
        return (base * factor).quantize(Decimal("0.01"))

    amount_attr = "discount_amount_usd" if currency == "USD" else "discount_amount_eur"
    amount = getattr(option, amount_attr, None)
    if amount:
        amount = Decimal(amount) if not isinstance(amount, Decimal) else amount
        return max(base - amount, Decimal("0")).quantize(Decimal("0.01"))

    return base.quantize(Decimal("0.01"))


def _validate_discount_combination(
    percent: int | None,
    amount_usd: Decimal | None,
    amount_eur: Decimal | None,
) -> None:
    if percent is not None and (amount_usd is not None or amount_eur is not None):
        raise ValueError("discount_percent and discount_amount_* are mutually exclusive")
    if (amount_usd is None) != (amount_eur is None):
        raise ValueError("discount_amount_usd and discount_amount_eur must be provided together")
    if percent is not None and not (1 <= percent <= 100):
        raise ValueError("discount_percent must be between 1 and 100")
    if amount_usd is not None and amount_usd <= 0:
        raise ValueError("discount_amount_usd must be greater than 0")
    if amount_eur is not None and amount_eur <= 0:
        raise ValueError("discount_amount_eur must be greater than 0")


class WhatYouGetItem(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    lead: str = Field(default="", max_length=1000)
    items: list[str] = Field(default_factory=list)


class SectionItem(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    texts: list[str] = Field(default_factory=list)


class ServiceOptionBase(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    price_usd: PriceField
    price_eur: PriceField
    is_default: bool = False
    sort_order: int = Field(default=0, ge=0)
    discount_percent: int | None = Field(default=None)
    discount_amount_usd: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    discount_amount_eur: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)

    @field_serializer("price_usd", "price_eur")
    def _serialize_price(self, value: Decimal) -> float:
        return float(value)

    @field_serializer("discount_amount_usd", "discount_amount_eur")
    def _serialize_discount_amount(self, value: Decimal | None) -> float | None:
        return None if value is None else float(value)

    @model_validator(mode="after")
    def _validate_discount(self) -> "ServiceOptionBase":
        _validate_discount_combination(
            self.discount_percent, self.discount_amount_usd, self.discount_amount_eur
        )
        return self


class ServiceOptionCreate(ServiceOptionBase):
    pass


class ServiceOptionUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    price_usd: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    price_eur: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    is_default: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)
    discount_percent: int | None = Field(default=None)
    discount_amount_usd: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    discount_amount_eur: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)

    @model_validator(mode="after")
    def _validate_discount_payload(self) -> "ServiceOptionUpdate":
        # Only validate combinations that are actually present in the
        # payload; PATCH "absent" fields stay unchanged on the DB row.
        sent = self.model_fields_set
        if not (
            "discount_percent" in sent
            or "discount_amount_usd" in sent
            or "discount_amount_eur" in sent
        ):
            return self
        _validate_discount_combination(
            self.discount_percent, self.discount_amount_usd, self.discount_amount_eur
        )
        return self


class ServiceOptionRead(ServiceOptionBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    service_id: UUID
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def discounted_price_usd(self) -> float:
        return float(calculate_discounted_price(self, "USD"))

    @computed_field
    @property
    def discounted_price_eur(self) -> float:
        return float(calculate_discounted_price(self, "EUR"))


class GameSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str


class PublicGameSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str


class ServiceBase(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    platform: Platform
    image_desktop_url: str | None = Field(default=None, max_length=500)
    image_mobile_url: str | None = Field(default=None, max_length=500)
    image_alt: str | None = Field(default=None, max_length=300)
    description: list[str] = Field(default_factory=list)
    what_you_get: list[WhatYouGetItem] = Field(default_factory=list)
    sections: list[SectionItem] = Field(default_factory=list)
    seo_title: str | None = Field(default=None, max_length=300)
    seo_description: str | None = Field(default=None, max_length=500)
    is_featured: bool = False
    sort_order: int = Field(default=0, ge=0)
    is_active: bool = True


class ServiceCreate(ServiceBase):
    game_id: UUID
    slug: str = Field(min_length=2, max_length=150, pattern=SLUG_PATTERN)
    options: list[ServiceOptionCreate] = Field(default_factory=list)

    @field_validator("options")
    @classmethod
    def _at_most_one_default(cls, v: list[ServiceOptionCreate]) -> list[ServiceOptionCreate]:
        defaults = sum(1 for opt in v if opt.is_default)
        if defaults > 1:
            raise ValueError("Only one option can be marked as default")
        return v


class ServiceUpdate(BaseModel):
    slug: str | None = Field(default=None, min_length=2, max_length=150, pattern=SLUG_PATTERN)
    title: str | None = Field(default=None, min_length=2, max_length=300)
    platform: Platform | None = None
    image_desktop_url: str | None = Field(default=None, max_length=500)
    image_mobile_url: str | None = Field(default=None, max_length=500)
    image_alt: str | None = Field(default=None, max_length=300)
    description: list[str] | None = None
    what_you_get: list[WhatYouGetItem] | None = None
    sections: list[SectionItem] | None = None
    seo_title: str | None = Field(default=None, max_length=300)
    seo_description: str | None = Field(default=None, max_length=500)
    is_featured: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ServiceRead(ServiceBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    game_id: UUID
    game: GameSummary
    options_count: int = 0
    default_option_price_usd: Decimal | None = None
    default_option_price_eur: Decimal | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("default_option_price_usd", "default_option_price_eur")
    def _serialize_optional_decimal(self, value: Decimal | None) -> float | None:
        return None if value is None else float(value)


class ServiceDetailRead(ServiceRead):
    options: list[ServiceOptionRead]


class PublicServiceOptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    label: str
    price_usd: Decimal
    price_eur: Decimal
    is_default: bool
    sort_order: int
    discount_percent: int | None = None
    discount_amount_usd: Decimal | None = None
    discount_amount_eur: Decimal | None = None

    @field_serializer("price_usd", "price_eur")
    def _serialize_price(self, value: Decimal) -> float:
        return float(value)

    @field_serializer("discount_amount_usd", "discount_amount_eur")
    def _serialize_discount_amount(self, value: Decimal | None) -> float | None:
        return None if value is None else float(value)

    @computed_field
    @property
    def discounted_price_usd(self) -> float:
        return float(calculate_discounted_price(self, "USD"))

    @computed_field
    @property
    def discounted_price_eur(self) -> float:
        return float(calculate_discounted_price(self, "EUR"))


class PublicServiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    title: str
    platform: Platform
    image_desktop_url: str | None
    image_mobile_url: str | None
    image_alt: str | None
    description: list[str]
    what_you_get: list[WhatYouGetItem]
    sections: list[SectionItem]
    seo_title: str | None
    seo_description: str | None
    is_featured: bool
    options: list[PublicServiceOptionRead]
    game: PublicGameSummary


class ReorderItem(BaseModel):
    id: UUID
    sort_order: int = Field(ge=0)


class ReorderRequest(BaseModel):
    items: list[ReorderItem] = Field(min_length=1)


class ReorderResponse(BaseModel):
    updated: int
