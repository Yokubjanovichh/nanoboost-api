"""EcomTrade24 provider — hosted-card checkout.

Phase 1 shipped the surface area (registry wiring + webhook signature
verification + payload parser). Phase 4 adds the live HTTP integration:

- `create_session` enforces the provider's $10 minimum, builds the
  documented payload and translates upstream error codes into
  Russian-facing messages.
- Logging never echoes the API key, the bearer header or webhook
  signatures — only stable order identifiers.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx

from app.core.config import settings
from app.core.exceptions import InvalidPaymentError, PaymentProviderError
from app.shared.payments.base import (
    CheckoutSession,
    PaymentProvider,
    WebhookEvent,
)

if TYPE_CHECKING:
    from app.features.orders.models import Order


logger = logging.getLogger("nanoboost.payments.ecomtrade24")

PROVIDER_NAME = "ecomtrade24"

# Provider error codes → user-friendly Russian messages. Anything not in this
# map falls through to a generic "Ошибка платёжной системы: <code>" so the
# operator can grep logs against the exact upstream code.
_ERROR_MESSAGES: dict[str, str] = {
    "invalid_domain": ("Платёжный сервис не сконфигурирован. Свяжитесь с поддержкой."),
    "valid_customer_email_required": "Укажите корректный email.",
    "missing_merchant_payout_wallet": (
        "Платёжный сервис временно недоступен. Свяжитесь с поддержкой."
    ),
    "rate_limited": "Слишком много попыток. Подождите минуту.",
}


class EcomTrade24Provider(PaymentProvider):
    name = PROVIDER_NAME
    MIN_AMOUNT_USD: Decimal = Decimal("10.00")
    REQUEST_TIMEOUT_SECONDS: float = 15.0

    async def create_session(
        self, order: Order, *, return_url: str, cancel_url: str
    ) -> CheckoutSession:
        # Provider rejects sub-$10 attempts upstream — fail fast with a
        # message the customer can act on instead of bubbling a 502.
        if order.final_total_usd < self.MIN_AMOUNT_USD:
            raise InvalidPaymentError(
                f"Минимальная сумма для оплаты картой — ${self.MIN_AMOUNT_USD}. "
                f"Сумма заказа: ${order.final_total_usd}. "
                "Выберите другой способ оплаты или добавьте товаров в корзину."
            )

        if not settings.ECOMTRADE24_API_KEY:
            raise PaymentProviderError(
                "Платёжный сервис не сконфигурирован. Свяжитесь с поддержкой."
            )

        payload = {
            "amount": str(order.final_total_usd),
            "currency": order.display_currency.value,
            "domain": settings.ECOMTRADE24_DOMAIN,
            "order_id": order.order_number,
            "email": order.client.email,
            "method": "card",
            "return_url": return_url,
            "cancel_url": cancel_url,
        }
        headers = {
            "Authorization": f"Bearer {settings.ECOMTRADE24_API_KEY}",
            "Content-Type": "application/json",
        }
        url = f"{settings.ECOMTRADE24_BASE_URL}/gateway/session.php"

        try:
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.warning(
                "EcomTrade24 timeout: order=%s amount=%s",
                order.order_number,
                order.final_total_usd,
            )
            raise PaymentProviderError("EcomTrade24 не отвечает. Попробуйте позже.") from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "EcomTrade24 transport error: order=%s err=%s",
                order.order_number,
                exc.__class__.__name__,
            )
            raise PaymentProviderError(
                "Ошибка связи с платёжным сервисом. Попробуйте позже."
            ) from exc

        if response.status_code != 200:
            error_code = _extract_error_code(response)
            logger.warning(
                "EcomTrade24 non-200: order=%s status=%s code=%s",
                order.order_number,
                response.status_code,
                error_code,
            )
            user_msg = _ERROR_MESSAGES.get(
                error_code,
                f"Ошибка платёжной системы: {error_code}",
            )
            raise PaymentProviderError(user_msg)

        try:
            data = response.json()
        except ValueError as exc:
            logger.warning(
                "EcomTrade24 returned non-JSON 200: order=%s",
                order.order_number,
            )
            raise PaymentProviderError(
                "Платёжная сессия не создана. Свяжитесь с поддержкой."
            ) from exc

        if not data.get("ok") or not data.get("checkout_url") or not data.get("session_id"):
            logger.warning(
                "EcomTrade24 ok=False or missing fields: order=%s",
                order.order_number,
            )
            raise PaymentProviderError("Платёжная сессия не создана. Свяжитесь с поддержкой.")

        session = CheckoutSession(
            provider=self.name,
            session_id=str(data["session_id"]),
            checkout_url=str(data["checkout_url"]),
            expires_at=_parse_expires(data.get("expires_at")),
        )
        logger.info(
            "EcomTrade24 session created: order=%s session_id=%s amount=%s",
            order.order_number,
            session.session_id,
            order.final_total_usd,
        )
        return session

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        secret = settings.ECOMTRADE24_WEBHOOK_SECRET
        if not secret or not signature:
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.strip().lower())

    def parse_webhook_event(self, payload: dict) -> WebhookEvent:
        # EcomTrade24 wire field mapping (captured from a live test webhook
        # on 2026-05-23 — sample stored in tests/unit/test_payment_strategy.py):
        #   our event_type ← payload["event"]      (e.g. "payment.session")
        #   our event_id   ← f"{session_id}:{status}" — same state transition
        #                    produces the same id, so provider retries dedupe
        #                    naturally against the (provider, event_id) PK.
        #   our order ref  ← payload["order_id"]   (our NB-... echoed back)
        #   our status     ← payload["status"]     (paid/failed/test/expired/…)
        try:
            event_type = str(payload["event"])
            session_id = payload["session_id"]
        except (KeyError, TypeError) as exc:
            raise ValueError("EcomTrade24 webhook payload missing event/session_id") from exc

        status_raw = str(payload.get("status", "")).lower()
        event_id = f"{session_id}:{status_raw}"

        order_ref = payload.get("order_id")

        # Normalised values we care about downstream:
        #   "paid"    — successful capture
        #   "failed"  — declined / expired / cancelled
        #   "pending" — anything else (no-op for now; includes "test")
        if status_raw in {"paid", "succeeded", "success", "completed"}:
            status = "paid"
        elif status_raw in {"failed", "declined", "cancelled", "expired"}:
            status = "failed"
        else:
            status = "pending"

        return WebhookEvent(
            provider=PROVIDER_NAME,
            event_id=event_id,
            event_type=event_type,
            order_id=str(order_ref) if order_ref else None,
            status=status,
            raw_payload=payload,
        )


def _extract_error_code(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        try:
            data = response.json()
        except ValueError:
            return str(response.status_code)
        for key in ("error", "code", "detail"):
            value = data.get(key)
            if value:
                return str(value)
    return str(response.status_code)


def _parse_expires(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        # EcomTrade24 returns either "2026-05-09T10:30:00Z" or
        # "2026-05-09 10:30:00" — datetime.fromisoformat accepts the first
        # form natively and the space variant after a one-char rewrite.
        return datetime.fromisoformat(raw.replace(" ", "T").replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
