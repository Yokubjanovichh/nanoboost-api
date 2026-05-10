from typing import Annotated, TypeVar

from fastapi import Depends, Query
from pydantic import BaseModel, Field

T = TypeVar("T")


class PageParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def limit(self) -> int:
        return self.page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def get_page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


PaginationDep = Annotated[PageParams, Depends(get_page_params)]


class Paginated[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


def paginate[T](items: list[T], *, total: int, params: PageParams) -> Paginated[T]:
    pages = (total + params.page_size - 1) // params.page_size if total > 0 else 0
    return Paginated(
        items=items,
        total=total,
        page=params.page,
        page_size=params.page_size,
        pages=pages,
    )
