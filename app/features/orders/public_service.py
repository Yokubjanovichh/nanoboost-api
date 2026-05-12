from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import OrderStatus, PaymentMethod
from app.core.exceptions import ValidationFailureError
from app.features.clients.repository import ClientRepository
from app.features.games.repository import GameRepository
from app.features.orders.models import Order, OrderItem
from app.features.orders.public_schemas import PublicOrderCreate, PublicOrderItemCreate
from app.features.orders.repository import OrderRepository
from app.features.services.repository import ServiceOptionRepository, ServiceRepository
from app.shared.notifications import OrderNotifier, get_order_notifier

USDT_DISCOUNT_PERCENT = 5


class PublicOrderService:
    """Order creation flow used by the public website checkout.

    Trust nothing from the request body besides the IDs and quantities.
    Prices, snapshots, totals and discount percentage are all computed
    server-side from the live `services` / `service_options` tables.
    """

    def __init__(
        self, db: AsyncSession, notifier: OrderNotifier | None = None
    ) -> None:
        self.db = db
        self.repo = OrderRepository(db)
        self.clients = ClientRepository(db)
        self.services = ServiceRepository(db)
        self.options = ServiceOptionRepository(db)
        self.games = GameRepository(db)
        self.notifier = notifier or get_order_notifier()

    async def _resolve_item(
        self, payload: PublicOrderItemCreate
    ) -> tuple[Any, Any, dict]:
        service = await self.services.get_by_id(payload.service_id)
        if service is None or service.is_deleted or not service.is_active:
            raise ValidationFailureError(
                f"Service {payload.service_id} is not available"
            )

        option = await self.options.get_by_id(
            payload.option_id, service_id=service.id
        )
        if option is None:
            raise ValidationFailureError(
                f"Option {payload.option_id} does not belong to service {service.id}"
            )

        game = await self.games.get_by_id(service.game_id)
        snapshot = {
            "slug": service.slug,
            "title": service.title,
            "image_url": service.image_desktop_url,
            "platform": service.platform.value,
            "game_slug": game.slug if game else None,
        }
        return service, option, snapshot

    async def create(
        self,
        payload: PublicOrderCreate,
        *,
        background_tasks: BackgroundTasks | None = None,
    ) -> Order:
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
            _, option, snapshot = await self._resolve_item(item)
            qty = Decimal(item.quantity)
            line_total_usd = (option.price_usd * qty).quantize(Decimal("0.01"))
            line_total_eur = (option.price_eur * qty).quantize(Decimal("0.01"))
            subtotal_usd += line_total_usd

            items_data.append(
                OrderItem(
                    service_id=item.service_id,
                    option_id=item.option_id,
                    service_snapshot=snapshot,
                    option_label=option.label,
                    quantity=item.quantity,
                    unit_price_usd=option.price_usd,
                    unit_price_eur=option.price_eur,
                    total_price_usd=line_total_usd,
                    total_price_eur=line_total_eur,
                )
            )

        subtotal_usd = subtotal_usd.quantize(Decimal("0.01"))

        if payload.payment_method == PaymentMethod.USDT_TRC20:
            discount_percent = USDT_DISCOUNT_PERCENT
        else:
            discount_percent = 0
        discount_amount = (
            subtotal_usd * Decimal(discount_percent) / Decimal("100")
        ).quantize(Decimal("0.01"))
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
            discount_percent=discount_percent,
            final_total_usd=final_total,
            comment=payload.comment,
        )
        for item_obj in items_data:
            order.items.append(item_obj)

        await self.repo.add(order)
        await self.db.commit()

        reloaded = await self.repo.get_with_relations(order.id)
        result = reloaded if reloaded is not None else order

        if background_tasks is not None:
            background_tasks.add_task(self.notifier.notify_new_order, result)

        return result
