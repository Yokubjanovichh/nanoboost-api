from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    ORDER_STATUS_TRANSITIONS,
    OrderStatus,
    PaymentMethod,
)
from app.core.exceptions import (
    InvalidStatusTransitionError,
    NotFoundError,
    ValidationFailureError,
)
from app.features.clients.repository import ClientRepository
from app.features.games.repository import GameRepository
from app.features.orders.models import Order, OrderItem
from app.features.orders.repository import OrderRepository
from app.features.orders.schemas import (
    OrderInternalCreate,
    OrderItemCreate,
    OrderStats,
    OrderStatusUpdate,
    OrderUpdate,
    StatusBreakdown,
)
from app.features.services.repository import ServiceRepository
from app.shared.notifications import OrderNotifier, get_order_notifier


def assert_transition(current: OrderStatus, target: OrderStatus) -> None:
    if current == target:
        raise ValidationFailureError(
            f"Order is already in '{current.value}' status"
        )
    allowed = ORDER_STATUS_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidStatusTransitionError(current.value, target.value)


def _status_timestamp_field(status: OrderStatus) -> str | None:
    return {
        OrderStatus.PAID: "paid_at",
        OrderStatus.COMPLETED: "completed_at",
        OrderStatus.CANCELLED: "cancelled_at",
        OrderStatus.REFUNDED: "refunded_at",
    }.get(status)


class OrderService:
    def __init__(
        self, db: AsyncSession, notifier: OrderNotifier | None = None
    ) -> None:
        self.db = db
        self.repo = OrderRepository(db)
        self.clients = ClientRepository(db)
        self.services = ServiceRepository(db)
        self.games = GameRepository(db)
        self.notifier = notifier or get_order_notifier()

    async def list(
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
        return await self.repo.list_paginated(
            limit=limit,
            offset=offset,
            status=status,
            client_id=client_id,
            payment_method=payment_method,
            date_from=date_from,
            date_to=date_to,
            search=search,
            sort=sort,
        )

    async def get(self, order_id: UUID) -> Order:
        order = await self.repo.get_with_relations(order_id)
        if order is None:
            raise NotFoundError("Order")
        return order

    async def update(self, order_id: UUID, payload: OrderUpdate) -> Order:
        order = await self.get(order_id)

        if payload.comment is not None:
            order.comment = payload.comment
        if payload.admin_notes is not None:
            order.admin_notes = payload.admin_notes

        await self.db.commit()
        return await self._reload(order_id)

    async def change_status(
        self,
        order_id: UUID,
        payload: OrderStatusUpdate,
        *,
        background_tasks: BackgroundTasks | None = None,
    ) -> Order:
        order = await self.get(order_id)
        old_status = order.status
        assert_transition(old_status, payload.status)

        order.status = payload.status
        ts_field = _status_timestamp_field(payload.status)
        if ts_field is not None:
            setattr(order, ts_field, datetime.now(UTC))

        await self.db.commit()
        reloaded = await self._reload(order_id)

        if background_tasks is not None:
            background_tasks.add_task(
                self.notifier.notify_status_change,
                reloaded,
                old_status,
                payload.status,
            )
        return reloaded

    async def stats(self) -> OrderStats:
        raw = await self.repo.stats()
        return OrderStats(
            total_orders=raw["total_orders"],
            total_revenue_usd=raw["total_revenue_usd"],
            orders_today=raw["orders_today"],
            revenue_today_usd=raw["revenue_today_usd"],
            avg_order_value_usd=raw["avg_order_value_usd"],
            by_status=[
                StatusBreakdown(status=item["status"], count=item["count"])
                for item in raw["by_status"]
            ],
        )

    async def _build_snapshot(self, item: OrderItemCreate) -> dict:
        """Resolve a frozen snapshot of the chosen service.

        Preference order:
          1. live `services` row when `service_id` is supplied
          2. payload-provided `service_snapshot` (legacy / seeded data)
          3. otherwise → ValidationFailureError (no source for snapshot)
        """
        if item.service_id is not None:
            service_obj = await self.services.get_by_id(item.service_id)
            if service_obj is not None:
                game_obj = await self.games.get_by_id(service_obj.game_id)
                return {
                    "slug": service_obj.slug,
                    "title": service_obj.title,
                    "image_url": service_obj.image_url,
                    "platform": service_obj.platform.value,
                    "game_slug": game_obj.slug if game_obj else None,
                }

        if item.service_snapshot is not None:
            return item.service_snapshot.model_dump()

        raise ValidationFailureError(
            "Order item must reference a service_id or include a service_snapshot"
        )

    async def create_internal(self, payload: OrderInternalCreate) -> Order:
        """Internal order creation used by Phase 5 public endpoint and tests.

        Computes totals server-side, generates concurrency-safe order number,
        upserts client, freezes a service snapshot for each item.
        """
        if not payload.items:
            raise ValidationFailureError("Order must contain at least one item")

        client = await self.clients.get_or_create(
            email=payload.email,
            discord=payload.discord,
            telegram=payload.telegram,
            whatsapp=payload.whatsapp,
        )

        subtotal_usd = Decimal("0")
        items_data: list[OrderItem] = []
        for item in payload.items:
            qty = Decimal(item.quantity)
            line_total_usd = (item.unit_price_usd * qty).quantize(Decimal("0.01"))
            line_total_eur = (item.unit_price_eur * qty).quantize(Decimal("0.01"))
            subtotal_usd += line_total_usd

            snapshot = await self._build_snapshot(item)

            items_data.append(
                OrderItem(
                    service_id=item.service_id,
                    option_id=item.option_id,
                    service_snapshot=snapshot,
                    option_label=item.option_label,
                    quantity=item.quantity,
                    unit_price_usd=item.unit_price_usd,
                    unit_price_eur=item.unit_price_eur,
                    total_price_usd=line_total_usd,
                    total_price_eur=line_total_eur,
                )
            )

        subtotal_usd = subtotal_usd.quantize(Decimal("0.01"))
        discount_pct = Decimal(payload.discount_percent)
        discount_amount = (subtotal_usd * discount_pct / Decimal("100")).quantize(
            Decimal("0.01")
        )
        final_total = (subtotal_usd - discount_amount).quantize(Decimal("0.01"))

        order_number = await self.repo.reserve_next_order_number()

        order = Order(
            order_number=order_number,
            client_id=client.id,
            status=OrderStatus.PENDING,
            payment_method=payload.payment_method,
            display_currency=payload.display_currency,
            subtotal_usd=subtotal_usd,
            discount_amount_usd=discount_amount,
            discount_percent=payload.discount_percent,
            final_total_usd=final_total,
            comment=payload.comment,
        )
        for item_obj in items_data:
            order.items.append(item_obj)

        await self.repo.add(order)
        await self.db.commit()
        return await self._reload(order.id)

    async def _reload(self, order_id: UUID) -> Order:
        order = await self.repo.get_with_relations(order_id)
        if order is None:
            raise NotFoundError("Order")
        return order
