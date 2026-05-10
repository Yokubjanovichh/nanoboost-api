from fastapi import APIRouter, status

from app.core.dependencies import CurrentUser, DbSession
from app.features.auth.schemas import LoginRequest, RefreshRequest, TokenResponse
from app.features.auth.service import AuthService
from app.features.users.models import User
from app.features.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    service = AuthService(db)
    user = await service.authenticate(payload.email, payload.password)
    return service.build_token_response(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: DbSession) -> TokenResponse:
    return await AuthService(db).refresh(payload.refresh_token)


@router.get("/me", response_model=UserRead)
async def me(current_user: CurrentUser) -> User:
    return current_user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(_: CurrentUser) -> None:
    """V1: client-side logout (token discard). V2: Redis token blacklist."""
    return
