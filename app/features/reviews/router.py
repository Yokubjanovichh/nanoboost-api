from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import DbSession
from app.core.permissions import (
    require_admin_or_above,
    require_any_authenticated,
    require_manager_or_above,
)
from app.features.reviews.schemas import (
    PublicReviewRead,
    ReviewCreate,
    ReviewRead,
    ReviewReorderRequest,
    ReviewReorderResponse,
    ReviewUpdate,
)
from app.features.reviews.service import ReviewService
from app.features.users.models import User
from app.shared.pagination import Paginated, PaginationDep, paginate

router = APIRouter(prefix="/reviews", tags=["reviews"])

ReadAccess = Annotated[User, Depends(require_any_authenticated)]
ManagerAccess = Annotated[User, Depends(require_manager_or_above)]
AdminAccess = Annotated[User, Depends(require_admin_or_above)]


@router.get("", response_model=Paginated[ReviewRead])
async def list_reviews(
    db: DbSession,
    _: ReadAccess,
    page: PaginationDep,
    service_id: Annotated[UUID | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
    is_featured: Annotated[bool | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    sort: Annotated[str | None, Query()] = None,
) -> Paginated[ReviewRead]:
    items, total = await ReviewService(db).list(
        limit=page.limit,
        offset=page.offset,
        service_id=service_id,
        is_active=is_active,
        is_featured=is_featured,
        search=search,
        sort=sort,
    )
    return paginate(
        [ReviewRead.model_validate(r) for r in items], total=total, params=page
    )


@router.post("", response_model=ReviewRead, status_code=status.HTTP_201_CREATED)
async def create_review(
    payload: ReviewCreate, db: DbSession, _: ManagerAccess
) -> ReviewRead:
    review = await ReviewService(db).create(payload)
    return ReviewRead.model_validate(review)


@router.post("/reorder", response_model=ReviewReorderResponse)
async def reorder_reviews(
    payload: ReviewReorderRequest, db: DbSession, _: ManagerAccess
) -> ReviewReorderResponse:
    updated = await ReviewService(db).reorder(payload)
    return ReviewReorderResponse(updated=updated)


@router.get("/{review_id}", response_model=ReviewRead)
async def get_review(
    review_id: UUID, db: DbSession, _: ReadAccess
) -> ReviewRead:
    review = await ReviewService(db).get(review_id)
    return ReviewRead.model_validate(review)


@router.patch("/{review_id}", response_model=ReviewRead)
async def update_review(
    review_id: UUID,
    payload: ReviewUpdate,
    db: DbSession,
    _: ManagerAccess,
) -> ReviewRead:
    review = await ReviewService(db).update(review_id, payload)
    return ReviewRead.model_validate(review)


@router.patch("/{review_id}/toggle", response_model=ReviewRead)
async def toggle_review_active(
    review_id: UUID, db: DbSession, _: ManagerAccess
) -> ReviewRead:
    review = await ReviewService(db).toggle_active(review_id)
    return ReviewRead.model_validate(review)


@router.patch("/{review_id}/featured", response_model=ReviewRead)
async def toggle_review_featured(
    review_id: UUID, db: DbSession, _: ManagerAccess
) -> ReviewRead:
    review = await ReviewService(db).toggle_featured(review_id)
    return ReviewRead.model_validate(review)


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    review_id: UUID, db: DbSession, _: AdminAccess
) -> None:
    await ReviewService(db).soft_delete(review_id)


# --- Public ------------------------------------------------------------------

public_router = APIRouter(prefix="/public/reviews", tags=["public"])


@public_router.get("", response_model=list[PublicReviewRead])
async def list_public_reviews(
    db: DbSession,
    service_id: Annotated[UUID | None, Query()] = None,
    featured: Annotated[bool | None, Query()] = None,
) -> list[PublicReviewRead]:
    reviews = await ReviewService(db).list_public(
        service_id=service_id, featured=featured
    )
    return [PublicReviewRead.model_validate(r) for r in reviews]
