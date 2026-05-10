from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import TokenType
from app.core.exceptions import InactiveUserError, InvalidCredentialsError, TokenInvalidError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.features.auth.schemas import TokenResponse
from app.features.users.models import User
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserRead


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = UserRepository(db)

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.repo.get_by_email(email)
        if user is None or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()
        if not user.is_active:
            raise InactiveUserError()
        return user

    def build_token_response(self, user: User) -> TokenResponse:
        return TokenResponse(
            access_token=create_access_token(user.id, user.role),
            refresh_token=create_refresh_token(user.id, user.role),
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UserRead.model_validate(user),
        )

    async def refresh(self, refresh_token: str) -> TokenResponse:
        payload = decode_token(refresh_token, TokenType.REFRESH)
        raw_id = payload.get("sub")
        if not raw_id:
            raise TokenInvalidError()

        try:
            user_id = UUID(raw_id)
        except ValueError as exc:
            raise TokenInvalidError() from exc

        user = await self.repo.get_by_id(user_id)
        if user is None:
            raise TokenInvalidError("User not found")
        if not user.is_active:
            raise InactiveUserError()

        return self.build_token_response(user)
