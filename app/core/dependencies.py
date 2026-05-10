from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import TokenType
from app.core.exceptions import InactiveUserError, TokenInvalidError
from app.core.security import decode_token
from app.db.session import get_db
from app.features.users.models import User
from app.features.users.repository import UserRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=True)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DbSession,
) -> User:
    payload = decode_token(token, TokenType.ACCESS)
    raw_id = payload.get("sub")
    if not raw_id:
        raise TokenInvalidError()

    try:
        user_id = UUID(raw_id)
    except ValueError as exc:
        raise TokenInvalidError() from exc

    user = await UserRepository(db).get_by_id(user_id)
    if user is None:
        raise TokenInvalidError("User not found")
    if not user.is_active:
        raise InactiveUserError()

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
