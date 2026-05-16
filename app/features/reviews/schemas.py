from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ServiceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    title: str


class PublicServiceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    title: str
    platform: str


class ReviewBase(BaseModel):
    author_name: str = Field(min_length=1, max_length=100)
    rating: int = Field(ge=1, le=5)
    text: str = Field(min_length=10, max_length=2000)
    is_featured: bool = False
    sort_order: int = Field(default=0, ge=0)
    is_active: bool = True


class ReviewCreate(ReviewBase):
    service_id: UUID | None = None


class ReviewUpdate(BaseModel):
    author_name: str | None = Field(default=None, min_length=1, max_length=100)
    service_id: UUID | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    text: str | None = Field(default=None, min_length=10, max_length=2000)
    is_featured: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ReviewRead(ReviewBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    service_id: UUID | None
    service: ServiceSummary | None
    created_at: datetime
    updated_at: datetime


class PublicReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    author_name: str
    rating: int
    text: str
    is_featured: bool
    service: PublicServiceSummary | None
    created_at: datetime


class ReviewReorderItem(BaseModel):
    id: UUID
    sort_order: int = Field(ge=0)


class ReviewReorderRequest(BaseModel):
    items: list[ReviewReorderItem] = Field(min_length=1)


class ReviewReorderResponse(BaseModel):
    updated: int
