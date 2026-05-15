from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.features.orders.models import Order


@dataclass(frozen=True)
class CheckoutSession:
    """Result of `PaymentProvider.create_session`.

    The frontend redirects the customer to `checkout_url`. `session_id` is the
    provider-side reference we persist on the order so we can correlate
    later webhook events with our local record.
    """

    provider: str
    session_id: str
    checkout_url: str
    expires_at: datetime | None = None


@dataclass(frozen=True)
class WebhookEvent:
    """Normalised view of a provider webhook payload.

    `event_id` is the provider's unique event identifier — used together with
    `provider` as the idempotency key in `payment_webhook_events`.
    `order_id` is the *external reference* the provider echoes back: for us
    that's our `Order.order_number` (e.g. NB-20260509-1001), not the UUID PK.
    """

    provider: str
    event_id: str
    event_type: str
    order_id: str | None
    status: str
    raw_payload: dict = field(default_factory=dict)


class PaymentProvider(ABC):
    """Strategy interface for outbound payment integrations.

    Implementations live in `app.shared.payments.<provider>` and are wired
    into `registry.py`. Subclasses must be safe to instantiate at import
    time — credential lookups should happen inside the methods, not in
    `__init__`, so that missing config doesn't break the app boot.
    """

    name: str = "base"

    @abstractmethod
    async def create_session(
        self, order: Order, *, return_url: str, cancel_url: str
    ) -> CheckoutSession:
        """Create a hosted-checkout session for `order`.

        MUST raise `NotImplementedError` if credentials are missing rather
        than constructing a partial session — the router translates this
        into HTTP 503.
        """

    @abstractmethod
    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        """Constant-time HMAC verification. Returns True iff the signature
        matches the body under the provider's shared secret.
        """

    @abstractmethod
    def parse_webhook_event(self, payload: dict) -> WebhookEvent:
        """Translate a raw provider payload into our internal `WebhookEvent`.

        MUST be defensive: missing keys → ValueError so the router can return
        HTTP 400 instead of accidentally writing a partial idempotency row.
        """
