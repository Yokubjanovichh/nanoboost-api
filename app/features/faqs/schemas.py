from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_QUESTION_MIN = 1
_QUESTION_MAX = 500
_ANSWER_MIN = 1
_ANSWER_MAX = 10_000


def _strip_and_check(text: str, *, label: str, lo: int, hi: int) -> str:
    """Trim whitespace, then enforce length. Whitespace-only payloads fail
    the lower bound so the admin can't silently land an "empty" row."""
    stripped = text.strip()
    if len(stripped) < lo:
        raise ValueError(f"{label} must be at least {lo} character")
    if len(stripped) > hi:
        raise ValueError(f"{label} must be at most {hi} characters")
    return stripped


class FAQCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=_QUESTION_MIN, max_length=_QUESTION_MAX)
    answer: str = Field(min_length=_ANSWER_MIN, max_length=_ANSWER_MAX)
    order_index: int = 0
    is_active: bool = True

    @field_validator("question")
    @classmethod
    def _question_clean(cls, v: str) -> str:
        return _strip_and_check(v, label="question", lo=_QUESTION_MIN, hi=_QUESTION_MAX)

    @field_validator("answer")
    @classmethod
    def _answer_clean(cls, v: str) -> str:
        return _strip_and_check(v, label="answer", lo=_ANSWER_MIN, hi=_ANSWER_MAX)


class FAQUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str | None = Field(default=None, min_length=_QUESTION_MIN, max_length=_QUESTION_MAX)
    answer: str | None = Field(default=None, min_length=_ANSWER_MIN, max_length=_ANSWER_MAX)
    order_index: int | None = None
    is_active: bool | None = None

    @field_validator("question")
    @classmethod
    def _question_clean(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _strip_and_check(v, label="question", lo=_QUESTION_MIN, hi=_QUESTION_MAX)

    @field_validator("answer")
    @classmethod
    def _answer_clean(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _strip_and_check(v, label="answer", lo=_ANSWER_MIN, hi=_ANSWER_MAX)


class FAQRead(BaseModel):
    """Admin-facing — includes `is_active` and bookkeeping fields."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    game_slug: str
    question: str
    answer: str
    order_index: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PublicFAQRead(BaseModel):
    """Storefront-facing — `is_active` is implicit (only true rows ship)
    and we drop timestamps so the bundle stays compact."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    answer: str
    order_index: int


class PublicFAQListResponse(BaseModel):
    faqs: list[PublicFAQRead]


class FAQReorderItem(BaseModel):
    id: int
    order_index: int


class FAQReorderRequest(BaseModel):
    order: list[FAQReorderItem] = Field(min_length=1)


class FAQReorderResponse(BaseModel):
    updated: int
