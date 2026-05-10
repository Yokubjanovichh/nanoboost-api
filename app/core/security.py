from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.constants import TokenType, UserRole
from app.core.exceptions import TokenInvalidError

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def _create_token(
    *,
    user_id: UUID,
    role: UserRole,
    token_type: TokenType,
    expires_delta: timedelta,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role.value,
        "type": token_type.value,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: UUID, role: UserRole) -> str:
    return _create_token(
        user_id=user_id,
        role=role,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(user_id: UUID, role: UserRole) -> str:
    return _create_token(
        user_id=user_id,
        role=role,
        token_type=TokenType.REFRESH,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise TokenInvalidError() from exc

    if payload.get("type") != expected_type.value:
        raise TokenInvalidError("Invalid token type")

    return payload
