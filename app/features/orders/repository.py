from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import asc, desc, func, or_, select, text
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import DisplayCurrency, OrderStatus, PaymentMethod
from app.features.clients.models import Client
from app.features.orders.models import Order, OrderItem

ORDER_NUMBER_LOCK_KEY = 9119_5023_1001  # arbitrary 64-bit constant for advisory lock

_SORTABLE = {
    "created_at": Order.created_at,
    "final_total_usd": Order.final_total_usd,
    "order_number": Order.order_number,
}


def _parse_sort(sort: str | None):
    if not sort:
        return [desc(Order.created_at)]
    descending = sort.startswith("-")
    field = sort[1:] if descending else sort
    column = _SORTABLE.get(field)
    if column is None:
        return [desc(Order.created_at)]
    return [desc(column) if descending else asc(column)]


class OrderRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def reserve_next_order_number(self, *, today: date | None = None) -> str:
        today = today or datetime.now(UTC).date()
        prefix = f"NB-{today.strftime('%Y%m%d')}-"

        # Postgres advisory lock for safe concurrent generation.
        # SQLite (tests) doesn't support this; ignore quietly there.
        dialect = self.db.bind.dialect.name if self.db.bind else ""
        if dialect == "postgresql":
            await self.db.execute(
                text("SELECT pg_advisory_xact_lock(:k)"),
                {"k": ORDER_NUMBER_LOCK_KEY},
            )

        last = (
            await self.db.execute(
                select(Order.order_number)
                .where(Order.order_number.like(f"{prefix}%"))
                .order_by(desc(Order.order_number))
                .limit(1)
            )
        ).scalar_one_or_none()

        if last:
            try:
                seq = int(last.rsplit("-", 1)[1]) + 1
            except (ValueError, IndexError):
                seq = 1001
        else:
            seq = 1001

        return f"{prefix}{seq:04d}"

    async def list_paginated(
        self,
        *,
        limit: int,
        offset: int,
        status: OrderStatus | None = None,
        client_id: UUID | None = None,
        payment_method: PaymentMethod | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[tuple[Order, int]], int]:
        items_count = (
            select(func.count(OrderItem.id))
            .where(OrderItem.order_id == Order.id)
            .correlate(Order)
            .scalar_subquery()
            .label("items_count")
        )

        items_q = select(Order, items_count).options(selectinload(Order.client))
        count_q = select(func.count()).select_from(Order)

        if status is not None:
            items_q = items_q.where(Order.status == status)
            count_q = count_q.where(Order.status == status)
        if client_id is not None:
            items_q = items_q.where(Order.client_id == client_id)
            count_q = count_q.where(Order.client_id == client_id)
        if payment_method is not None:
            items_q = items_q.where(Order.payment_method == payment_method)
            count_q = count_q.where(Order.payment_method == payment_method)
        if date_from is not None:
            items_q = items_q.where(Order.created_at >= date_from)
            count_q = count_q.where(Order.created_at >= date_from)
        if date_to is not None:
            items_q = items_q.where(Order.created_at <= date_to)
            count_q = count_q.where(Order.created_at <= date_to)
        if search:
            pattern = f"%{search.strip()}%"
            items_q = items_q.join(Client, Client.id == Order.client_id)
            count_q = count_q.join(Client, Client.id == Order.client_id)
            cond = or_(
                Order.order_number.ilike(pattern),
                Client.email.ilike(pattern),
            )
            items_q = items_q.where(cond)
            count_q = count_q.where(cond)

        for clause in _parse_sort(sort):
            items_q = items_q.order_by(clause)

        items_q = items_q.limit(limit).offset(offset)

        rows = (await self.db.execute(items_q)).all()
        total = (await self.db.execute(count_q)).scalar_one()
        return [(row[0], int(row[1] or 0)) for row in rows], total

    async def get_by_id(self, order_id: UUID) -> Order | None:
        q = select(Order).where(Order.id == order_id)
        return (await self.db.execute(q)).scalar_one_or_none()

    async def get_with_relations(self, order_id: UUID) -> Order | None:
        q = (
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.client))
            .where(Order.id == order_id)
        )
        return (await self.db.execute(q)).scalar_one_or_none()

    async def add(self, order: Order) -> Order:
        self.db.add(order)
        await self.db.flush()
        return order

    async def stats(self, *, currency: DisplayCurrency = DisplayCurrency.USD) -> dict:
        del currency  # USD-only in V1; argument kept for forward compat

        # Total + revenue
        totals_row: Result = await self.db.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.final_total_usd), 0),
                func.coalesce(func.avg(Order.final_total_usd), 0),
            )
        )
        total_orders, total_revenue, avg_value = totals_row.one()

        # Today
        now = datetime.now(UTC)
        start_of_day = datetime(now.year, now.month, now.day, tzinfo=UTC)
        end_of_day = start_of_day + timedelta(days=1)
        today_row = await self.db.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.final_total_usd), 0),
            ).where(Order.created_at >= start_of_day, Order.created_at < end_of_day)
        )
        orders_today, revenue_today = today_row.one()

        # Breakdown by status
        breakdown_rows = (
            await self.db.execute(select(Order.status, func.count(Order.id)).group_by(Order.status))
        ).all()

        return {
            "total_orders": int(total_orders or 0),
            "total_revenue_usd": Decimal(str(total_revenue or 0)),
            "orders_today": int(orders_today or 0),
            "revenue_today_usd": Decimal(str(revenue_today or 0)),
            "avg_order_value_usd": Decimal(str(avg_value or 0)).quantize(Decimal("0.01")),
            "by_status": [
                {"status": status, "count": int(count or 0)} for status, count in breakdown_rows
            ],
        }
