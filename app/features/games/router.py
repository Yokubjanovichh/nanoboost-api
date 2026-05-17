from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.constants import GameStatus
from app.core.dependencies import DbSession
from app.core.permissions import (
    require_admin_or_above,
    require_any_authenticated,
    require_manager_or_above,
)
from app.features.games.schemas import (
    GameCreate,
    GameRead,
    GameUpdate,
    PublicGameRead,
    ReorderRequest,
    ReorderResponse,
)
from app.features.games.service import GameService
from app.features.users.models import User
from app.shared.cache import cached_response
from app.shared.pagination import Paginated, PaginationDep, paginate

router = APIRouter(prefix="/games", tags=["games"])

ReadAccess = Annotated[User, Depends(require_any_authenticated)]
ManagerAccess = Annotated[User, Depends(require_manager_or_above)]
AdminAccess = Annotated[User, Depends(require_admin_or_above)]


@router.get("", response_model=Paginated[GameRead])
async def list_games(
    db: DbSession,
    _: ReadAccess,
    page: PaginationDep,
    status: Annotated[GameStatus | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    sort: Annotated[str | None, Query()] = None,
) -> Paginated[GameRead]:
    items, total = await GameService(db).list(
        limit=page.limit,
        offset=page.offset,
        status=status,
        search=search,
        sort=sort,
    )
    return paginate([GameRead.model_validate(g) for g in items], total=total, params=page)


@router.post("", response_model=GameRead, status_code=status.HTTP_201_CREATED)
async def create_game(payload: GameCreate, db: DbSession, _: ManagerAccess) -> GameRead:
    game = await GameService(db).create(payload)
    return GameRead.model_validate(game)


@router.post("/reorder", response_model=ReorderResponse)
async def reorder_games(
    payload: ReorderRequest, db: DbSession, _: ManagerAccess
) -> ReorderResponse:
    updated = await GameService(db).reorder(payload)
    return ReorderResponse(updated=updated)


@router.get("/{game_id}", response_model=GameRead)
async def get_game(game_id: UUID, db: DbSession, _: ReadAccess) -> GameRead:
    game = await GameService(db).get(game_id)
    return GameRead.model_validate(game)


@router.patch("/{game_id}", response_model=GameRead)
async def update_game(
    game_id: UUID, payload: GameUpdate, db: DbSession, _: ManagerAccess
) -> GameRead:
    game = await GameService(db).update(game_id, payload)
    return GameRead.model_validate(game)


@router.delete("/{game_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_game(game_id: UUID, db: DbSession, _: AdminAccess) -> None:
    await GameService(db).soft_delete(game_id)


public_router = APIRouter(prefix="/public/games", tags=["public"])


@public_router.get("", response_model=list[PublicGameRead])
async def list_public_games(db: DbSession):
    """Returns a `Response` directly so cached requests skip Pydantic
    re-validation on the hot path. `response_model` stays for OpenAPI."""

    async def _build():
        rows = await GameService(db).list_public()
        return [
            PublicGameRead.model_validate(game)
            .model_copy(update={"service_count": count})
            .model_dump(mode="json")
            for game, count in rows
        ]

    return await cached_response(key="public:games:v1", ttl=300, build=_build)
