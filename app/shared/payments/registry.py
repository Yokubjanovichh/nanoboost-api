"""Provider registry — maps payment-method enum values to their adapters.

Routers should look up via `get_payment_provider(payment_method)` and treat
a `None` return as "this method is wallet-only / no hosted checkout"
(e.g. PayPal sandbox flow, USDT manual transfer).
"""

from __future__ import annotations

from app.core.constants import PaymentMethod
from app.shared.payments.base import PaymentProvider
from app.shared.payments.ecomtrade24 import EcomTrade24Provider

_PROVIDERS: dict[str, PaymentProvider] = {
    PaymentMethod.CARD_ECOMTRADE24.value: EcomTrade24Provider(),
}


def get_payment_provider(method: str | PaymentMethod) -> PaymentProvider | None:
    key = method.value if isinstance(method, PaymentMethod) else method
    return _PROVIDERS.get(key)
