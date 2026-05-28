from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import OrderStatus, PaymentMethod
from app.core.exceptions import NotFoundError, ValidationFailureError
from app.features.clients.repository import ClientRepository
from app.features.games.repository import GameRepository
from app.features.orders.models import Order, OrderItem
from app.features.orders.public_schemas import PublicOrderCreate, PublicOrderItemCreate
from app.features.orders.repository import OrderRepository
from app.features.services.repository import ServiceOptionRepository, ServiceRepository
from app.features.services.schemas import calculate_discounted_price
from app.shared.notifications import OrderNotifier, get_order_notifier

USDT_DISCOUNT_PERCENT = 5


class PublicOrderService:
    """Order creation flow used by the public website checkout.

    Trust nothing from the request body besides the IDs and quantities.
    Prices, snapshots, totals and discount percentage are all computed
    server-side from the live `services` / `service_options` tables.
    """

    def __init__(self, db: AsyncSession, notifier: OrderNotifier | None = None) -> None:
        self.db = db
        self.repo = OrderRepository(db)
        self.clients = ClientRepository(db)
        self.services = ServiceRepository(db)
        self.options = ServiceOptionRepository(db)
        self.games = GameRepository(db)
        self.notifier = notifier or get_order_notifier()

    async def _resolve_item(self, payload: PublicOrderItemCreate) -> tuple[Any, Any, dict]:
        # Slug, not UUID — see PublicOrderItemCreate. `get_by_slug` already
        # filters soft-deleted rows; we still need the explicit `is_active`
        # check because admins use that flag to hide a service from the
        # public surface without deleting it.
        service = await self.services.get_by_slug(payload.service_slug)
        if service is None or not service.is_active:
            raise NotFoundError(f"Service '{payload.service_slug}'")

        option = await self.options.get_by_id(payload.option_id, service_id=service.id)
        if option is None:
            raise ValidationFailureError(
                f"Option {payload.option_id} does not belong to service '{payload.service_slug}'"
            )

        game = await self.games.get_by_id(service.game_id)
        snapshot = {
            "slug": service.slug,
            "title": service.title,
            "image_url": service.image_desktop_url,
            "platform": service.platform.value,
            "game_slug": game.slug if game else None,
            # Option-level audit trail. The discounted prices are also
            # stored on OrderItem.unit_price_* (so reports don't need to
            # re-derive them); these fields exist for audit after a price
            # or discount change on the live ServiceOption row.
            "option": {
                "label": option.label,
                "original_price_usd": str(option.price_usd),
                "original_price_eur": str(option.price_eur),
                # Decimals are stringified for JSONB portability — the snapshot
                # is consumed by reports / admin UI which can re-parse to
                # Decimal if needed. Plain `None` stays plain `None`.
                "discount_percent": (
                    str(option.discount_percent) if option.discount_percent is not None else None
                ),
                "discount_amount_usd": (
                    str(option.discount_amount_usd)
                    if option.discount_amount_usd is not None
                    else None
                ),
                "discount_amount_eur": (
                    str(option.discount_amount_eur)
                    if option.discount_amount_eur is not None
                    else None
                ),
            },
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
        subtotal_eur = Decimal("0")
        items_data: list[OrderItem] = []
        for item in payload.items:
            service, option, snapshot = await self._resolve_item(item)
            qty = Decimal(item.qty)
            # Item-level discount is applied here so the order subtotal
            # already reflects per-option discounts. The order-level USDT
            # 5% (if any) then stacks naturally on the discounted subtotal.
            unit_usd = calculate_discounted_price(option, "USD")
            unit_eur = calculate_discounted_price(option, "EUR")
            line_total_usd = (unit_usd * qty).quantize(Decimal("0.01"))
            line_total_eur = (unit_eur * qty).quantize(Decimal("0.01"))
            subtotal_usd += line_total_usd
            subtotal_eur += line_total_eur

            items_data.append(
                OrderItem(
                    service_id=service.id,
                    option_id=item.option_id,
                    service_snapshot=snapshot,
                    option_label=option.label,
                    quantity=item.qty,
                    unit_price_usd=unit_usd,
                    unit_price_eur=unit_eur,
                    total_price_usd=line_total_usd,
                    total_price_eur=line_total_eur,
                )
            )

        subtotal_usd = subtotal_usd.quantize(Decimal("0.01"))
        subtotal_eur = subtotal_eur.quantize(Decimal("0.01"))

        if payload.payment_method == PaymentMethod.USDT_TRC20:
            discount_percent = USDT_DISCOUNT_PERCENT
        else:
            discount_percent = 0
        discount_factor = Decimal(discount_percent) / Decimal("100")
        discount_amount = (subtotal_usd * discount_factor).quantize(Decimal("0.01"))
        # Apply the same percentage to EUR so the FE-visible totals stay
        # consistent across currencies. Quantize independently — rounding
        # USD then converting via a rate would drift on small orders.
        discount_amount_eur = (subtotal_eur * discount_factor).quantize(Decimal("0.01"))
        final_total = (subtotal_usd - discount_amount).quantize(Decimal("0.01"))
        final_total_eur = (subtotal_eur - discount_amount_eur).quantize(Decimal("0.01"))

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
            final_total_eur=final_total_eur,
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
