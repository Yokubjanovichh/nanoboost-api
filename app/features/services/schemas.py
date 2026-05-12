from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)

from app.core.constants import Platform

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
PriceField = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]


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

    @field_serializer("price_usd", "price_eur")
    def _serialize_price(self, value: Decimal) -> float:
        return float(value)


class ServiceOptionCreate(ServiceOptionBase):
    pass


class ServiceOptionUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    price_usd: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    price_eur: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    is_default: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)


class ServiceOptionRead(ServiceOptionBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    service_id: UUID
    created_at: datetime
    updated_at: datetime


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

    @field_serializer("price_usd", "price_eur")
    def _serialize_price(self, value: Decimal) -> float:
        return float(value)


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
