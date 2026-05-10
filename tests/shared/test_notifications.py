from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.constants import DisplayCurrency, OrderStatus, PaymentMethod
from app.shared.notifications.base import NoOpBackend
from app.shared.notifications.email import SmtpEmailBackend
from app.shared.notifications.orders import OrderNotifier
from app.shared.notifications.telegram import TelegramBackend


def _fake_order(**overrides):
    """Build an Order-like object suitable for notifier formatters."""
    from datetime import UTC, datetime

    client = SimpleNamespace(
        email="buyer@example.com",
        discord="buyer#1234",
        telegram="@buyer",
        whatsapp=None,
    )
    item = SimpleNamespace(
        service_snapshot={"slug": "gta-cash-ps", "title": "GTA Cash Boost PS4/PS5"},
        option_label="20 million",
        quantity=1,
        total_price_usd=Decimal("19.99"),
    )
    base = {
        "order_number": "NB-20260509-1001",
        "status": OrderStatus.PENDING,
        "payment_method": PaymentMethod.USDT_TRC20,
        "display_currency": DisplayCurrency.USD,
        "subtotal_usd": Decimal("19.99"),
        "discount_amount_usd": Decimal("1.00"),
        "discount_percent": 5,
        "final_total_usd": Decimal("18.99"),
        "comment": "Срочный заказ",
        "admin_notes": None,
        "created_at": datetime(2026, 5, 9, 10, 30, tzinfo=UTC),
        "client": client,
        "items": [item],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# --- Backend tests -----------------------------------------------------------


def _patch_telegram_transport(
    transport: httpx.MockTransport, monkeypatch
) -> TelegramBackend:
    """Inject httpx MockTransport without recursion."""
    from app.shared.notifications import telegram as tg_module

    real_cls = httpx.AsyncClient

    def _factory(*_args, **_kwargs):
        return real_cls(transport=transport)

    monkeypatch.setattr(tg_module.httpx, "AsyncClient", _factory)
    return TelegramBackend(token="TKN", chat_id="42")


@pytest.mark.asyncio
async def test_telegram_send_success(monkeypatch) -> None:
    transport = httpx.MockTransport(
        lambda _r: httpx.Response(200, json={"ok": True})
    )
    backend = _patch_telegram_transport(transport, monkeypatch)
    assert await backend.send(body="hello") is True


@pytest.mark.asyncio
async def test_telegram_send_failure_returns_false(monkeypatch) -> None:
    def _handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    transport = httpx.MockTransport(_handler)
    backend = _patch_telegram_transport(transport, monkeypatch)
    assert await backend.send(body="hello") is False


@pytest.mark.asyncio
async def test_telegram_non_200_returns_false(monkeypatch) -> None:
    transport = httpx.MockTransport(
        lambda _r: httpx.Response(401, json={"ok": False, "description": "bad"})
    )
    backend = _patch_telegram_transport(transport, monkeypatch)
    assert await backend.send(body="hello") is False


@pytest.mark.asyncio
async def test_email_send_success() -> None:
    backend = SmtpEmailBackend(
        host="smtp.test", port=587,
        username="u", password="p",
        sender="from@x", recipient="to@x",
    )
    with patch("aiosmtplib.send", new=AsyncMock(return_value=None)) as mock_send:
        ok = await backend.send(subject="S", body="B")
    assert ok is True
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_email_send_failure_returns_false() -> None:
    backend = SmtpEmailBackend(
        host="smtp.test", port=587,
        username="u", password="p",
        sender="from@x", recipient="to@x",
    )
    with patch("aiosmtplib.send", new=AsyncMock(side_effect=ConnectionRefusedError())):
        ok = await backend.send(subject="S", body="B")
    assert ok is False


@pytest.mark.asyncio
async def test_noop_backend_always_true() -> None:
    backend = NoOpBackend()
    assert await backend.send(subject="any", body="any") is True


# --- OrderNotifier tests -----------------------------------------------------


@pytest.mark.asyncio
async def test_notifier_dispatches_both_channels() -> None:
    tg = AsyncMock()
    tg.send = AsyncMock(return_value=True)
    em = AsyncMock()
    em.send = AsyncMock(return_value=True)

    notifier = OrderNotifier(telegram=tg, email=em)
    await notifier.notify_new_order(_fake_order())

    assert tg.send.await_count == 1
    assert em.send.await_count == 1


@pytest.mark.asyncio
async def test_notifier_telegram_failure_does_not_break_email() -> None:
    tg = AsyncMock()
    tg.send = AsyncMock(side_effect=RuntimeError("oops"))
    em = AsyncMock()
    em.send = AsyncMock(return_value=True)

    notifier = OrderNotifier(telegram=tg, email=em)
    # MUST NOT raise
    await notifier.notify_new_order(_fake_order())

    assert em.send.await_count == 1


@pytest.mark.asyncio
async def test_notifier_status_change_includes_old_and_new_label() -> None:
    tg = AsyncMock()
    tg.send = AsyncMock(return_value=True)
    em = AsyncMock()
    em.send = AsyncMock(return_value=True)

    notifier = OrderNotifier(telegram=tg, email=em)
    await notifier.notify_status_change(
        _fake_order(status=OrderStatus.PAID),
        OrderStatus.PENDING,
        OrderStatus.PAID,
    )
    body = tg.send.await_args.kwargs.get("body") or tg.send.await_args.args[0]
    assert "В ожидании" in body
    assert "Оплачен" in body


def test_format_telegram_new_order_contains_key_fields() -> None:
    notifier = OrderNotifier(telegram=NoOpBackend(), email=NoOpBackend())
    body = notifier._format_telegram_new_order(_fake_order())
    assert "*НОВЫЙ ЗАКАЗ*" in body
    assert "NB-20260509-1001" in body
    assert "buyer@examplecom" in body or "buyer@example" in body  # MD-stripped
    assert "USDT (TRC20)" in body
    assert "$18.99" in body
    assert "5%" in body
    assert "GTA Cash Boost PS4PS5" in body or "GTA Cash Boost" in body


# --- Factory: disabled config returns NoOpBackend ---------------------------


def test_factory_returns_noop_when_notifications_disabled(monkeypatch) -> None:
    from app.shared.notifications import (
        get_email_backend,
        get_telegram_backend,
    )

    monkeypatch.setattr(
        "app.shared.notifications.settings.NOTIFICATIONS_ENABLED", False
    )
    assert isinstance(get_telegram_backend(), NoOpBackend)
    assert isinstance(get_email_backend(), NoOpBackend)


def test_factory_returns_noop_when_telegram_token_missing(monkeypatch) -> None:
    from app.shared.notifications import get_telegram_backend

    monkeypatch.setattr(
        "app.shared.notifications.settings.NOTIFICATIONS_ENABLED", True
    )
    monkeypatch.setattr("app.shared.notifications.settings.TG_ENABLED", True)
    monkeypatch.setattr("app.shared.notifications.settings.TG_BOT_TOKEN", "")
    monkeypatch.setattr("app.shared.notifications.settings.TG_CHAT_ID", "")
    assert isinstance(get_telegram_backend(), NoOpBackend)


def test_factory_returns_telegram_when_configured(monkeypatch) -> None:
    from app.shared.notifications import get_telegram_backend

    monkeypatch.setattr(
        "app.shared.notifications.settings.NOTIFICATIONS_ENABLED", True
    )
    monkeypatch.setattr("app.shared.notifications.settings.TG_ENABLED", True)
    monkeypatch.setattr("app.shared.notifications.settings.TG_BOT_TOKEN", "TKN")
    monkeypatch.setattr("app.shared.notifications.settings.TG_CHAT_ID", "42")
    assert isinstance(get_telegram_backend(), TelegramBackend)
