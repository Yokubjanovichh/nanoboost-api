from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import DbSession
from app.core.permissions import require_any_authenticated
from app.features.dashboard.schemas import (
    DashboardOverview,
    PeriodEnum,
    RecentOrdersResponse,
    RevenueChartResponse,
    TopServicesResponse,
)
from app.features.dashboard.service import DashboardService
from app.features.orders.schemas import OrderRead
from app.features.users.models import User

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

ReadAccess = Annotated[User, Depends(require_any_authenticated)]


def _to_order_read(order, items_count: int) -> OrderRead:
    base = OrderRead.model_validate(order)
    return base.model_copy(update={"items_count": items_count})


@router.get("/overview", response_model=DashboardOverview)
async def get_overview(
    db: DbSession,
    _: ReadAccess,
    period: Annotated[PeriodEnum, Query()] = PeriodEnum.MONTH,
) -> DashboardOverview:
    return await DashboardService(db).overview(period)


@router.get("/revenue-chart", response_model=RevenueChartResponse)
async def get_revenue_chart(
    db: DbSession,
    _: ReadAccess,
    period: Annotated[PeriodEnum, Query()] = PeriodEnum.MONTH,
) -> RevenueChartResponse:
    return await DashboardService(db).revenue_chart(period)


@router.get("/top-services", response_model=TopServicesResponse)
async def get_top_services(
    db: DbSession,
    _: ReadAccess,
    period: Annotated[PeriodEnum, Query()] = PeriodEnum.MONTH,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> TopServicesResponse:
    return await DashboardService(db).top_services(period, limit=limit)


@router.get("/recent-orders", response_model=RecentOrdersResponse)
async def get_recent_orders(
    db: DbSession,
    _: ReadAccess,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> RecentOrdersResponse:
    orders = await DashboardService(db).recent_orders(limit=limit)
    items = [
        _to_order_read(o, items_count=0) for o in orders
    ]
    return RecentOrdersResponse(items=items)
