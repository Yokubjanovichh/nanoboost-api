from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from app.core.constants import OrderStatus, PaymentMethod
from app.shared.notifications.base import NotificationBackend

if TYPE_CHECKING:
    from app.features.orders.models import Order

logger = logging.getLogger("nanoboost.notifications.orders")

STATUS_LABEL_RU: dict[OrderStatus, str] = {
    OrderStatus.PENDING: "Ожидает оплату",
    OrderStatus.PAID: "Оплачен",
    OrderStatus.AWAITING_BOOSTER: "Ожидает бустера",
    OrderStatus.IN_PROGRESS: "В работе",
    OrderStatus.BOOSTER_COMPLETED: "Выполнен бустером",
    OrderStatus.DELIVERED_TO_CLIENT: "Выдан клиенту",
    OrderStatus.COMPLETED: "Завершен",
    OrderStatus.CANCELLED: "Отменен",
    OrderStatus.REFUNDED: "Возврат провайдером",
}

PAYMENT_LABEL: dict[PaymentMethod, str] = {
    PaymentMethod.PAYPAL: "PayPal",
    PaymentMethod.USDT_TRC20: "USDT (TRC20)",
}

# Strip Markdown special chars to keep safety simple — no rendering tricks.
_MD_SAFE = re.compile(r"[_*\[\]()`~>#+=|{}.!\\-]")


def _md_safe(value: str | None) -> str:
    if not value:
        return "-"
    return _MD_SAFE.sub("", value)


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y %H:%M UTC")


def _fmt_money(amount: Decimal | float, currency: str = "$") -> str:
    return f"{currency}{float(amount):.2f}"


class OrderNotifier:
    """Dispatches new-order and status-change notifications across channels.

    Each channel is best-effort: failure is logged, never re-raised.
    """

    def __init__(
        self,
        telegram: NotificationBackend,
        email: NotificationBackend,
    ) -> None:
        self.telegram = telegram
        self.email = email

    async def notify_new_order(self, order: Order) -> None:
        try:
            tg_body = self._format_telegram_new_order(order)
            email_subj = f"Nanoboost — Новый заказ {order.order_number}"
            email_body = self._format_email_new_order(order)

            await asyncio.gather(
                self.telegram.send(subject="", body=tg_body),
                self.email.send(subject=email_subj, body=email_body),
                return_exceptions=True,
            )
        except Exception:
            logger.exception(
                "notify_new_order failed for order %s",
                getattr(order, "order_number", "<unknown>"),
            )

    async def notify_payment_claim(self, order: Order) -> None:
        """Customer clicked "I have paid" on a PayPal / USDT order.

        Telegram-only — the admin verifies the wallet/PayPal balance and
        marks the order PAID from the admin panel. Email channel is
        intentionally skipped: this is a low-latency operator nudge, not
        a customer-facing receipt.
        """
        try:
            tg_body = self._format_telegram_payment_claim(order)
            await self.telegram.send(subject="", body=tg_body)
        except Exception:
            logger.exception(
                "notify_payment_claim failed for order %s",
                getattr(order, "order_number", "<unknown>"),
            )

    async def notify_status_change(
        self,
        order: Order,
        old_status: OrderStatus,
        new_status: OrderStatus,
    ) -> None:
        try:
            tg_body = self._format_telegram_status_change(order, old_status, new_status)
            email_subj = f"Nanoboost — Обновление статуса {order.order_number}"
            email_body = self._format_email_status_change(order, old_status, new_status)

            await asyncio.gather(
                self.telegram.send(subject="", body=tg_body),
                self.email.send(subject=email_subj, body=email_body),
                return_exceptions=True,
            )
        except Exception:
            logger.exception(
                "notify_status_change failed for order %s",
                getattr(order, "order_number", "<unknown>"),
            )

    # --- Formatters ---------------------------------------------------------

    def _format_telegram_new_order(self, order: Order) -> str:
        client = order.client
        contact_lines = [f"📧 Email: {_md_safe(client.email)}"]
        if client.discord:
            contact_lines.append(f"💬 Discord: {_md_safe(client.discord)}")
        if client.telegram:
            contact_lines.append(f"✈️ Telegram: {_md_safe(client.telegram)}")
        if client.whatsapp:
            contact_lines.append(f"📱 WhatsApp: {_md_safe(client.whatsapp)}")

        items_lines = []
        for item in order.items:
            title = (item.service_snapshot or {}).get("title") or "Service"
            label = item.option_label or "-"
            line_total = _fmt_money(item.total_price_usd)
            items_lines.append(
                f"  • {_md_safe(title)} ({_md_safe(label)}) ×{item.quantity} — {line_total}"
            )

        body_lines = [
            "🛒 *НОВЫЙ ЗАКАЗ*",
            "",
            f"🔢 Заказ: *{order.order_number}*",
            f"🕐 Время: {_fmt_dt(order.created_at)}",
            "",
            *contact_lines,
            f"💳 Оплата: {PAYMENT_LABEL.get(order.payment_method, order.payment_method)}",
            f"💱 Валюта: {order.display_currency.value}",
            "",
            "📦 Услуги:",
            *items_lines,
            "",
            f"📋 Подытог: {_fmt_money(order.subtotal_usd)}",
        ]
        if order.discount_percent:
            body_lines.append(
                f"🏷️ Скидка (-{order.discount_percent}%): -{_fmt_money(order.discount_amount_usd)}"
            )
        body_lines.append(f"💰 Итого: *{_fmt_money(order.final_total_usd)}*")
        if order.comment:
            body_lines += ["", f"📝 Комментарий: {_md_safe(order.comment)}"]
        return "\n".join(body_lines)

    def _format_telegram_payment_claim(self, order: Order) -> str:
        client = order.client
        method_label = PAYMENT_LABEL.get(order.payment_method, str(order.payment_method))
        # Show the customer-chosen currency total. USD is canonical; EUR
        # is the snapshot from order creation (NULL on pre-migration-0011
        # rows, but those orders predate this endpoint).
        if order.display_currency.value == "EUR" and order.final_total_eur is not None:
            amount = _fmt_money(order.final_total_eur, currency="€")
        else:
            amount = _fmt_money(order.final_total_usd)
        claimed_at = order.payment_claimed_at or datetime.now(UTC)
        lines = [
            "🔔 *ПОДТВЕРЖДЕНИЕ ОПЛАТЫ — нужна проверка*",
            "",
            f"🔢 Заказ: *{order.order_number}*",
            f"💳 Метод: {method_label}",
            f"💰 Сумма: *{amount}*",
            "",
            f"📧 Email: {_md_safe(client.email)}",
        ]
        if client.discord:
            lines.append(f"💬 Discord: {_md_safe(client.discord)}")
        if client.telegram:
            lines.append(f"✈️ Telegram: {_md_safe(client.telegram)}")
        if client.whatsapp:
            lines.append(f"📱 WhatsApp: {_md_safe(client.whatsapp)}")
        lines += [
            "",
            f"⏰ Заявлено: {_fmt_dt(claimed_at)}",
            "",
            f"⚠️ Проверьте поступление в {method_label} и отметьте заказ как ОПЛАЧЕН в админке.",
        ]
        return "\n".join(lines)

    def _format_telegram_status_change(
        self,
        order: Order,
        old_status: OrderStatus,
        new_status: OrderStatus,
    ) -> str:
        old_label = STATUS_LABEL_RU.get(old_status, str(old_status))
        new_label = STATUS_LABEL_RU.get(new_status, str(new_status))
        lines = [
            "📦 *СТАТУС ИЗМЕНЁН*",
            "",
            f"🔢 Заказ: *{order.order_number}*",
            f"⏪ Старый: {old_label}",
            f"⏩ Новый: *{new_label}*",
            f"🕐 {_fmt_dt(datetime.now(UTC))}",
        ]
        if order.admin_notes:
            lines += ["", f"📝 Заметки: {_md_safe(order.admin_notes)}"]
        return "\n".join(lines)

    def _format_email_new_order(self, order: Order) -> str:
        client = order.client
        contact = [f"  Email: {client.email}"]
        if client.discord:
            contact.append(f"  Discord: {client.discord}")
        if client.telegram:
            contact.append(f"  Telegram: {client.telegram}")
        if client.whatsapp:
            contact.append(f"  WhatsApp: {client.whatsapp}")

        items = []
        for item in order.items:
            title = (item.service_snapshot or {}).get("title") or "Service"
            label = item.option_label or "-"
            items.append(
                f"  • {title} ({label}) ×{item.quantity} — {_fmt_money(item.total_price_usd)}"
            )

        lines = [
            f"Новый заказ: {order.order_number}",
            f"Время: {_fmt_dt(order.created_at)}",
            "",
            "Клиент:",
            *contact,
            "",
            f"Способ оплаты: {PAYMENT_LABEL.get(order.payment_method, order.payment_method)}",
            f"Валюта: {order.display_currency.value}",
            "",
            "Услуги:",
            *items,
            "",
            f"Подытог: {_fmt_money(order.subtotal_usd)}",
        ]
        if order.discount_percent:
            lines.append(
                f"Скидка (-{order.discount_percent}%): -{_fmt_money(order.discount_amount_usd)}"
            )
        lines.append(f"Итого: {_fmt_money(order.final_total_usd)}")
        if order.comment:
            lines += ["", f"Комментарий: {order.comment}"]
        return "\n".join(lines)

    def _format_email_status_change(
        self,
        order: Order,
        old_status: OrderStatus,
        new_status: OrderStatus,
    ) -> str:
        old_label = STATUS_LABEL_RU.get(old_status, str(old_status))
        new_label = STATUS_LABEL_RU.get(new_status, str(new_status))
        lines = [
            f"Заказ: {order.order_number}",
            f"Старый статус: {old_label}",
            f"Новый статус: {new_label}",
            f"Время: {_fmt_dt(datetime.now(UTC))}",
        ]
        if order.admin_notes:
            lines += ["", f"Заметки: {order.admin_notes}"]
        return "\n".join(lines)
