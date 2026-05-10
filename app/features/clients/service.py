from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.features.clients.models import Client
from app.features.clients.repository import ClientRepository
from app.features.clients.schemas import ClientRead, ClientStats, ClientUpdate, ClientWithStats
from app.features.orders.models import Order


class ClientService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ClientRepository(db)

    async def get(self, client_id: UUID) -> Client:
        client = await self.repo.get_by_id(client_id)
        if client is None:
            raise NotFoundError("Client")
        return client

    async def get_with_stats(self, client_id: UUID) -> ClientWithStats:
        client = await self.get(client_id)
        total_orders, total_spent, first_at, last_at = await self.repo.stats_for(client.id)
        base_data = ClientRead.model_validate(client).model_dump()
        return ClientWithStats(
            **base_data,
            stats=ClientStats(
                total_orders=total_orders,
                total_spent_usd=total_spent,
                first_order_at=first_at,
                last_order_at=last_at,
            ),
        )

    async def list(
        self, *, limit: int, offset: int, search: str | None = None
    ) -> tuple[list[Client], int]:
        return await self.repo.list_paginated(limit=limit, offset=offset, search=search)

    async def list_orders(
        self, client_id: UUID, *, limit: int, offset: int
    ) -> tuple[list[Order], int]:
        await self.get(client_id)
        return await self.repo.list_orders(client_id, limit=limit, offset=offset)

    async def update(self, client_id: UUID, payload: ClientUpdate) -> Client:
        client = await self.get(client_id)

        if payload.discord is not None:
            client.discord = payload.discord
        if payload.telegram is not None:
            client.telegram = payload.telegram
        if payload.whatsapp is not None:
            client.whatsapp = payload.whatsapp
        if payload.notes is not None:
            client.notes = payload.notes

        await self.db.commit()
        await self.db.refresh(client)
        return client
