from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.dependencies import DbSession
from app.core.permissions import require_admin_or_above, require_manager_or_above
from app.features.faqs.schemas import (
    FAQCreate,
    FAQRead,
    FAQReorderRequest,
    FAQReorderResponse,
    FAQUpdate,
    PublicFAQListResponse,
    PublicFAQRead,
)
from app.features.faqs.service import FAQService
from app.features.users.models import User

ManagerAccess = Annotated[User, Depends(require_manager_or_above)]
AdminAccess = Annotated[User, Depends(require_admin_or_above)]


# --- Public router --------------------------------------------------------
# Lives under /api/v1/public/* alongside the other storefront reads
# (/public/games, /public/services/{slug}, /public/reviews) so the FE
# can apply a single auth/CORS rule to that whole surface.

public_router = APIRouter(prefix="/public/games", tags=["public"])


@public_router.get("/{game_slug}/faqs", response_model=PublicFAQListResponse)
async def list_public_faqs(game_slug: str, db: DbSession) -> PublicFAQListResponse:
    """Unknown game_slug returns `{"faqs": []}` (not 404) so the storefront
    can render the section unconditionally."""
    items = await FAQService(db).list_public(game_slug)
    return PublicFAQListResponse(faqs=[PublicFAQRead.model_validate(i) for i in items])


# --- Admin router ---------------------------------------------------------

router = APIRouter(prefix="/admin", tags=["admin-faqs"])


@router.get("/games/{game_slug}/faqs", response_model=list[FAQRead])
async def list_admin_faqs(game_slug: str, db: DbSession, _: ManagerAccess) -> list[FAQRead]:
    items = await FAQService(db).list_admin(game_slug)
    return [FAQRead.model_validate(i) for i in items]


@router.post(
    "/games/{game_slug}/faqs",
    response_model=FAQRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_faq(
    game_slug: str, payload: FAQCreate, db: DbSession, _: ManagerAccess
) -> FAQRead:
    faq = await FAQService(db).create(game_slug, payload)
    return FAQRead.model_validate(faq)


@router.post(
    "/games/{game_slug}/faqs/reorder",
    response_model=FAQReorderResponse,
)
async def reorder_admin_faqs(
    game_slug: str,
    payload: FAQReorderRequest,
    db: DbSession,
    _: ManagerAccess,
) -> FAQReorderResponse:
    updated = await FAQService(db).reorder(game_slug, payload)
    return FAQReorderResponse(updated=updated)


@router.patch("/faqs/{faq_id}", response_model=FAQRead)
async def update_admin_faq(
    faq_id: int, payload: FAQUpdate, db: DbSession, _: ManagerAccess
) -> FAQRead:
    faq = await FAQService(db).update(faq_id, payload)
    return FAQRead.model_validate(faq)


@router.delete("/faqs/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_faq(faq_id: int, db: DbSession, _: AdminAccess) -> None:
    """Hard delete — destructive, gated behind admin role (same posture
    as game soft-delete; FAQs have no audit trail to preserve)."""
    await FAQService(db).delete(faq_id)
