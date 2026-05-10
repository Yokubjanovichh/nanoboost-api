from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import hash_password
from app.features.users.models import User
from app.features.users.repository import UserRepository
from app.features.users.schemas import UserCreate, UserUpdate


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = UserRepository(db)

    async def create(self, payload: UserCreate) -> User:
        existing = await self.repo.get_by_email(payload.email)
        if existing is not None:
            raise ConflictError("User with this email already exists")

        user = User(
            email=payload.email.lower(),
            password_hash=hash_password(payload.password),
            full_name=payload.full_name,
            role=payload.role,
            is_active=True,
        )
        await self.repo.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def get(self, user_id: UUID) -> User:
        user = await self.repo.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User")
        return user

    async def list(self, *, limit: int, offset: int) -> tuple[list[User], int]:
        return await self.repo.list_paginated(limit=limit, offset=offset)

    async def update(self, user_id: UUID, payload: UserUpdate) -> User:
        user = await self.get(user_id)

        if payload.full_name is not None:
            user.full_name = payload.full_name
        if payload.role is not None:
            user.role = payload.role
        if payload.is_active is not None:
            user.is_active = payload.is_active
        if payload.password is not None:
            user.password_hash = hash_password(payload.password)

        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def deactivate(self, user_id: UUID) -> None:
        user = await self.get(user_id)
        user.is_active = False
        await self.db.commit()
