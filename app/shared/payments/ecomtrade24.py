"""EcomTrade24 provider skeleton.

Phase 1 ships only the surface area: class structure, signature shape, and
config wiring. Real HTTP calls + HMAC verification land in Phase 4 once the
provider sandbox credentials are confirmed.

Until then:
- `create_session` raises NotImplementedError → router returns HTTP 503.
- `verify_webhook_signature` returns False until the secret is configured,
  so webhook endpoint rejects everything as Unauthorized.
- `parse_webhook_event` is implemented against the documented shape and
  guarded by tests in this Phase already, so the idempotency contract is
  locked in even before live traffic.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import TYPE_CHECKING

from app.core.config import settings
from app.shared.payments.base import (
    CheckoutSession,
    PaymentProvider,
    WebhookEvent,
)

if TYPE_CHECKING:
    from app.features.orders.models import Order


PROVIDER_NAME = "ecomtrade24"


class EcomTrade24Provider(PaymentProvider):
    name = PROVIDER_NAME

    async def create_session(
        self, order: Order, *, return_url: str, cancel_url: str
    ) -> CheckoutSession:
        # Phase 4 will: POST {ECOMTRADE24_BASE_URL}/api/sessions with
        # {amount, currency, order_id=order.order_number, return_url, cancel_url}
        # using ECOMTRADE24_API_KEY auth. Until then we surface a clear
        # "not configured yet" signal to the router.
        del order, return_url, cancel_url
        raise NotImplementedError("EcomTrade24 checkout session creation is not configured yet")

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        secret = settings.ECOMTRADE24_WEBHOOK_SECRET
        if not secret or not signature:
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.strip().lower())

    def parse_webhook_event(self, payload: dict) -> WebhookEvent:
        try:
            event_id = str(payload["event_id"])
            event_type = str(payload["event_type"])
        except (KeyError, TypeError) as exc:
            raise ValueError("EcomTrade24 webhook payload missing event_id/event_type") from exc

        # Provider echoes our `order_number` back as `external_reference`.
        order_ref = payload.get("external_reference") or payload.get("order_id")

        status_raw = str(payload.get("status", "")).lower()
        # Normalised values we care about downstream:
        #   "paid"    — successful capture
        #   "failed"  — declined / expired / cancelled
        #   "pending" — anything else (no-op for now)
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
