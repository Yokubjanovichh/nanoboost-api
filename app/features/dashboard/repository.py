from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.features.clients.models import Client
from app.features.orders.models import Order, OrderItem
from app.features.services.models import Service


class DashboardRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def overview_totals(
        self, *, from_dt: datetime, to_dt: datetime
    ) -> tuple[int, Decimal, Decimal]:
        row = (
            await self.db.execute(
                select(
                    func.count(Order.id),
                    func.coalesce(func.sum(Order.final_total_usd), 0),
                    func.coalesce(func.avg(Order.final_total_usd), 0),
                ).where(Order.created_at >= from_dt, Order.created_at < to_dt)
            )
        ).one()
        total_orders = int(row[0] or 0)
        total_revenue = Decimal(str(row[1] or 0)).quantize(Decimal("0.01"))
        avg_value = Decimal(str(row[2] or 0)).quantize(Decimal("0.01"))
        return total_orders, total_revenue, avg_value

    async def overview_new_clients(self, *, from_dt: datetime, to_dt: datetime) -> int:
        row = await self.db.execute(
            select(func.count(Client.id)).where(
                Client.created_at >= from_dt, Client.created_at < to_dt
            )
        )
        return int(row.scalar_one() or 0)

    async def overview_by_status(self, *, from_dt: datetime, to_dt: datetime) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(Order.status, func.count(Order.id))
                .where(Order.created_at >= from_dt, Order.created_at < to_dt)
                .group_by(Order.status)
            )
        ).all()
        return {str(status.value): int(count or 0) for status, count in rows}

    async def overview_by_payment_method(
        self, *, from_dt: datetime, to_dt: datetime
    ) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(Order.payment_method, func.count(Order.id))
                .where(Order.created_at >= from_dt, Order.created_at < to_dt)
                .group_by(Order.payment_method)
            )
        ).all()
        return {str(method.value): int(count or 0) for method, count in rows}

    async def revenue_per_day(self, *, from_dt: datetime, to_dt: datetime) -> dict:
        """Returns {date_obj: (revenue_decimal, orders_count)} for non-empty days."""
        # Cross-dialect: cast created_at to date.
        date_col = func.date(Order.created_at).label("d")
        rows = (
            await self.db.execute(
                select(
                    date_col,
                    func.coalesce(func.sum(Order.final_total_usd), 0),
                    func.count(Order.id),
                )
                .where(Order.created_at >= from_dt, Order.created_at < to_dt)
                .group_by(date_col)
            )
        ).all()
        result: dict = {}
        for row_date, revenue, count in rows:
            # SQLite returns ISO string, Postgres returns date object.
            if isinstance(row_date, str):
                from datetime import date as _date

                row_date = _date.fromisoformat(row_date)
            result[row_date] = (
                Decimal(str(revenue or 0)).quantize(Decimal("0.01")),
                int(count or 0),
            )
        return result

    async def top_services(self, *, from_dt: datetime, to_dt: datetime, limit: int) -> list[tuple]:
        """Returns rows: (service_id, slug, title, orders_count, revenue_usd)."""
        q = (
            select(
                Service.id.label("service_id"),
                Service.slug,
                Service.title,
                func.count(func.distinct(OrderItem.order_id)).label("orders_count"),
                func.coalesce(func.sum(OrderItem.total_price_usd), 0).label("revenue_usd"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .join(Service, Service.id == OrderItem.service_id)
            .where(
                Order.created_at >= from_dt,
                Order.created_at < to_dt,
            )
            .group_by(Service.id, Service.slug, Service.title)
            .order_by(desc("revenue_usd"))
            .limit(limit)
        )
        rows = (await self.db.execute(q)).all()
        return [
            (
                row.service_id,
                row.slug,
                row.title,
                int(row.orders_count or 0),
                Decimal(str(row.revenue_usd or 0)).quantize(Decimal("0.01")),
            )
            for row in rows
        ]

    async def recent_orders(self, *, limit: int) -> list[Order]:
        q = (
            select(Order)
            .options(selectinload(Order.client))
            .order_by(desc(Order.created_at))
            .limit(limit)
        )
        return list((await self.db.execute(q)).scalars().all())


def date_range(period: str, *, now: datetime) -> tuple[datetime, datetime]:
    """Return [from_dt, to_dt) as a half-open interval in UTC."""
    to_dt = now
    if period == "today":
        from_dt = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
    elif period == "week":
        from_dt = now - timedelta(days=7)
    elif period == "year":
        from_dt = now - timedelta(days=365)
    else:  # month / default
        from_dt = now - timedelta(days=30)
    return from_dt, to_dt
