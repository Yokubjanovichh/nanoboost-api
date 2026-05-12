from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.features.clients.models import Client
from app.features.orders.models import Order


class ClientRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, client_id: UUID) -> Client | None:
        result = await self.db.execute(select(Client).where(Client.id == client_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Client | None:
        result = await self.db.execute(select(Client).where(Client.email == email.lower()))
        return result.scalar_one_or_none()

    async def list_paginated(
        self, *, limit: int, offset: int, search: str | None = None
    ) -> tuple[list[Client], int]:
        items_q = select(Client).order_by(desc(Client.created_at))
        count_q = select(func.count()).select_from(Client)

        if search:
            pattern = f"%{search.strip()}%"
            cond = or_(
                Client.email.ilike(pattern),
                Client.discord.ilike(pattern),
                Client.telegram.ilike(pattern),
            )
            items_q = items_q.where(cond)
            count_q = count_q.where(cond)

        items_q = items_q.limit(limit).offset(offset)

        items = (await self.db.execute(items_q)).scalars().all()
        total = (await self.db.execute(count_q)).scalar_one()
        return list(items), total

    async def add(self, client: Client) -> Client:
        self.db.add(client)
        await self.db.flush()
        await self.db.refresh(client)
        return client

    async def get_or_create(
        self,
        *,
        email: str,
        discord: str | None = None,
        telegram: str | None = None,
        whatsapp: str | None = None,
    ) -> Client:
        existing = await self.get_by_email(email)
        if existing is not None:
            # Refresh contact fields if newer values supplied
            if discord and not existing.discord:
                existing.discord = discord
            if telegram and not existing.telegram:
                existing.telegram = telegram
            if whatsapp and not existing.whatsapp:
                existing.whatsapp = whatsapp
            return existing
        client = Client(
            email=email.lower(),
            discord=discord,
            telegram=telegram,
            whatsapp=whatsapp,
        )
        return await self.add(client)

    async def stats_for(
        self, client_id: UUID
    ) -> tuple[int, Decimal, datetime | None, datetime | None]:
        q = select(
            func.count(Order.id),
            func.coalesce(func.sum(Order.final_total_usd), 0),
            func.min(Order.created_at),
            func.max(Order.created_at),
        ).where(Order.client_id == client_id)
        result = (await self.db.execute(q)).one()
        total_orders, total_spent, first_at, last_at = result
        return int(total_orders or 0), Decimal(str(total_spent or 0)), first_at, last_at

    async def list_orders(
        self, client_id: UUID, *, limit: int, offset: int
    ) -> tuple[list[Order], int]:
        items_q = (
            select(Order)
            .options(selectinload(Order.client))
            .where(Order.client_id == client_id)
            .order_by(desc(Order.created_at))
            .limit(limit)
            .offset(offset)
        )
        count_q = select(func.count()).select_from(Order).where(Order.client_id == client_id)
        items = (await self.db.execute(items_q)).scalars().all()
        total = (await self.db.execute(count_q)).scalar_one()
        return list(items), total
