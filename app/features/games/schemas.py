from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import GameStatus

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class GameBase(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    image_desktop_url: str | None = Field(default=None, max_length=500)
    image_mobile_url: str | None = Field(default=None, max_length=500)
    sort_order: int = Field(default=0, ge=0)
    status: GameStatus = GameStatus.ACTIVE


class GameCreate(GameBase):
    slug: str = Field(min_length=2, max_length=100, pattern=SLUG_PATTERN)


class GameUpdate(BaseModel):
    slug: str | None = Field(default=None, min_length=2, max_length=100, pattern=SLUG_PATTERN)
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = None
    image_desktop_url: str | None = Field(default=None, max_length=500)
    image_mobile_url: str | None = Field(default=None, max_length=500)
    sort_order: int | None = Field(default=None, ge=0)
    status: GameStatus | None = None


class GameRead(GameBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    created_at: datetime
    updated_at: datetime


class PublicGameRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    description: str | None
    image_desktop_url: str | None
    image_mobile_url: str | None
    status: GameStatus


class ReorderItem(BaseModel):
    id: UUID
    sort_order: int = Field(ge=0)


class ReorderRequest(BaseModel):
    items: list[ReorderItem] = Field(min_length=1)


class ReorderResponse(BaseModel):
    updated: int
