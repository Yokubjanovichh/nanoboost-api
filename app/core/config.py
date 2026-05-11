from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    ENVIRONMENT: Literal["dev", "test", "prod"] = "dev"

    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://nanoboost:nanoboost@postgres:5432/nanoboost"
    )

    # Railway/Heroku Postgres plugins inject sync-style URLs
    # (postgresql://… or postgres://…). The app and Alembic env both use
    # asyncpg, so rewrite the scheme up-front rather than expecting every
    # provider to be reconfigured by hand.
    @field_validator("DATABASE_URL")
    @classmethod
    def _ensure_async_driver(cls, value: str) -> str:
        for sync_prefix in ("postgresql://", "postgres://"):
            if value.startswith(sync_prefix):
                return "postgresql+asyncpg://" + value[len(sync_prefix):]
        return value

    JWT_SECRET_KEY: str = Field(min_length=32)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    SEED_SUPERUSER_EMAIL: str = "admin@nanoboost.io"
    SEED_SUPERUSER_PASSWORD: str = "ChangeMeImmediately123!"
    SEED_SUPERUSER_NAME: str = "Root Admin"

    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    UPLOADS_DIR: str = "uploads"
    UPLOADS_URL_PREFIX: str = "/uploads"
    MAX_UPLOAD_SIZE_BYTES: int = 5 * 1024 * 1024
    ALLOWED_UPLOAD_FOLDERS: list[str] = Field(
        default_factory=lambda: ["games", "services", "reviews", "misc"]
    )

    NOTIFICATIONS_ENABLED: bool = True
    TG_ENABLED: bool = True
    TG_BOT_TOKEN: str = ""
    TG_CHAT_ID: str = ""
    SMTP_ENABLED: bool = True
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "orders@nanoboost.io"
    NOTIFY_EMAIL: str = "admin@nanoboost.io"

    @property
    def is_dev(self) -> bool:
        return self.ENVIRONMENT == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
