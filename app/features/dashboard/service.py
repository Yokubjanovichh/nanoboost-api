from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.dashboard.repository import DashboardRepository, date_range
from app.features.dashboard.schemas import (
    DashboardOverview,
    PeriodEnum,
    RevenueChartItem,
    RevenueChartResponse,
    TopServiceItem,
    TopServicesResponse,
)
from app.features.orders.models import Order


class DashboardService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = DashboardRepository(db)

    async def overview(self, period: PeriodEnum) -> DashboardOverview:
        now = datetime.now(UTC)
        from_dt, to_dt = date_range(period.value, now=now)

        total_orders, total_revenue, avg_value = await self.repo.overview_totals(
            from_dt=from_dt, to_dt=to_dt
        )
        new_clients = await self.repo.overview_new_clients(
            from_dt=from_dt, to_dt=to_dt
        )
        by_status = await self.repo.overview_by_status(
            from_dt=from_dt, to_dt=to_dt
        )
        by_payment_method = await self.repo.overview_by_payment_method(
            from_dt=from_dt, to_dt=to_dt
        )

        return DashboardOverview(
            period=period,
            from_date=from_dt,
            to_date=to_dt,
            total_orders=total_orders,
            total_revenue_usd=total_revenue,
            average_order_value_usd=avg_value,
            new_clients=new_clients,
            by_status=by_status,
            by_payment_method=by_payment_method,
        )

    async def revenue_chart(self, period: PeriodEnum) -> RevenueChartResponse:
        now = datetime.now(UTC)
        from_dt, to_dt = date_range(period.value, now=now)
        per_day = await self.repo.revenue_per_day(from_dt=from_dt, to_dt=to_dt)

        items: list[RevenueChartItem] = []
        cursor = from_dt.date()
        end_day = to_dt.date()
        while cursor <= end_day:
            revenue, count = per_day.get(cursor, (Decimal("0.00"), 0))
            items.append(
                RevenueChartItem(
                    date=cursor,
                    revenue_usd=revenue,
                    orders_count=count,
                )
            )
            cursor += timedelta(days=1)

        return RevenueChartResponse(period=period, items=items)

    async def top_services(
        self, period: PeriodEnum, *, limit: int
    ) -> TopServicesResponse:
        now = datetime.now(UTC)
        from_dt, to_dt = date_range(period.value, now=now)
        rows = await self.repo.top_services(
            from_dt=from_dt, to_dt=to_dt, limit=limit
        )
        items = [
            TopServiceItem(
                service_id=row[0],
                slug=row[1],
                title=row[2],
                orders_count=row[3],
                revenue_usd=row[4],
            )
            for row in rows
        ]
        return TopServicesResponse(period=period, items=items)

    async def recent_orders(self, *, limit: int) -> list[Order]:
        return await self.repo.recent_orders(limit=limit)
