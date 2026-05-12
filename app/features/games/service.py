from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.features.games.models import Game
from app.features.games.repository import GameRepository
from app.features.games.schemas import (
    GameCreate,
    GameUpdate,
    ReorderRequest,
)


class GameService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = GameRepository(db)

    async def create(self, payload: GameCreate) -> Game:
        if await self.repo.get_by_slug(payload.slug) is not None:
            raise ConflictError("Game with this slug already exists")

        game = Game(
            slug=payload.slug,
            name=payload.name,
            description=payload.description,
            image_desktop_url=payload.image_desktop_url,
            image_mobile_url=payload.image_mobile_url,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
        )
        await self.repo.add(game)
        await self.db.commit()
        await self.db.refresh(game)
        return game

    async def get(self, game_id: UUID) -> Game:
        game = await self.repo.get_by_id(game_id)
        if game is None:
            raise NotFoundError("Game")
        return game

    async def list(
        self,
        *,
        limit: int,
        offset: int,
        is_active: bool | None = None,
        search: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[Game], int]:
        return await self.repo.list_paginated(
            limit=limit, offset=offset, is_active=is_active, search=search, sort=sort
        )

    async def list_public(self) -> list[Game]:
        return await self.repo.list_public()

    async def update(self, game_id: UUID, payload: GameUpdate) -> Game:
        game = await self.get(game_id)

        if payload.slug is not None and payload.slug != game.slug:
            existing = await self.repo.get_by_slug(payload.slug, exclude_id=game.id)
            if existing is not None:
                raise ConflictError("Game with this slug already exists")
            game.slug = payload.slug

        if payload.name is not None:
            game.name = payload.name
        if payload.description is not None:
            game.description = payload.description
        if payload.image_desktop_url is not None:
            game.image_desktop_url = payload.image_desktop_url
        if payload.image_mobile_url is not None:
            game.image_mobile_url = payload.image_mobile_url
        if payload.sort_order is not None:
            game.sort_order = payload.sort_order
        if payload.is_active is not None:
            game.is_active = payload.is_active

        await self.db.commit()
        await self.db.refresh(game)
        return game

    async def toggle_active(self, game_id: UUID) -> Game:
        game = await self.get(game_id)
        game.is_active = not game.is_active
        await self.db.commit()
        await self.db.refresh(game)
        return game

    async def soft_delete(self, game_id: UUID) -> None:
        game = await self.get(game_id)
        game.is_deleted = True
        game.is_active = False
        await self.db.commit()

    async def reorder(self, payload: ReorderRequest) -> int:
        pairs = [(item.id, item.sort_order) for item in payload.items]
        updated = await self.repo.bulk_update_sort_order(pairs)
        if updated == 0:
            raise NotFoundError("None of the games")
        await self.db.commit()
        return updated
