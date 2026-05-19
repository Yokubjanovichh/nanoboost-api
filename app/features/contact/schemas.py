from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class PreferredContact(StrEnum):
    DISCORD = "discord"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    EMAIL = "email"


class ContactSubmissionCreate(BaseModel):
    """Wire payload accepted on POST /api/v1/public/contact.

    Trim-on-input via `field_validator(mode="before")` so a user who pads
    their handle with whitespace doesn't get bounced by `min_length`.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    preferred_contact: PreferredContact
    handle: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    message: str = Field(min_length=10, max_length=2000)

    @field_validator("handle", "message", mode="before")
    @classmethod
    def _coerce_str(cls, value):
        # `str_strip_whitespace` runs *after* min/max checks in pydantic v2
        # for some field types; trim here so a 10-char message of pure
        # spaces still bounces 422.
        if isinstance(value, str):
            return value.strip()
        return value

    @model_validator(mode="after")
    def _email_required_when_preferred(self):
        if self.preferred_contact is PreferredContact.EMAIL and not self.email:
            raise ValueError(
                "email is required when preferred_contact is 'email'",
            )
        return self


class ContactSubmissionResponse(BaseModel):
    """PII-free response — the frontend only needs the success signal."""

    status: str = "ok"
