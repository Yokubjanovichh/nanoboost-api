from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.users.models import User


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()

    async def list_paginated(self, *, limit: int, offset: int) -> tuple[list[User], int]:
        items_q = select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
        total_q = select(func.count()).select_from(User)

        items = (await self.db.execute(items_q)).scalars().all()
        total = (await self.db.execute(total_q)).scalar_one()
        return list(items), total

    async def add(self, user: User) -> User:
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def save(self) -> None:
        await self.db.flush()

    async def commit(self) -> None:
        await self.db.commit()
