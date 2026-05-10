from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.core.dependencies import DbSession
from app.core.permissions import require_superadmin
from app.features.users.models import User
from app.features.users.schemas import UserCreate, UserRead, UserUpdate
from app.features.users.service import UserService
from app.shared.pagination import Paginated, PaginationDep, paginate

router = APIRouter(prefix="/users", tags=["users"])

SuperadminUser = Annotated[User, Depends(require_superadmin)]


@router.get("", response_model=Paginated[UserRead])
async def list_users(
    db: DbSession,
    _: SuperadminUser,
    page: PaginationDep,
) -> Paginated[UserRead]:
    items, total = await UserService(db).list(limit=page.limit, offset=page.offset)
    return paginate([UserRead.model_validate(u) for u in items], total=total, params=page)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: DbSession,
    _: SuperadminUser,
) -> User:
    return await UserService(db).create(payload)


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: UUID,
    db: DbSession,
    _: SuperadminUser,
) -> User:
    return await UserService(db).get(user_id)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    db: DbSession,
    _: SuperadminUser,
) -> User:
    return await UserService(db).update(user_id, payload)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: UUID,
    db: DbSession,
    _: SuperadminUser,
) -> None:
    await UserService(db).deactivate(user_id)
