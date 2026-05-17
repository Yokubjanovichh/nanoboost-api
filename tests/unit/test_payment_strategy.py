"""Provider registry + EcomTrade24 webhook signature.

The signature check is what stops a forged webhook from flipping an
order to PAID, so we cover it explicitly. The registry lookup is
trivial but worth pinning so a future provider rename doesn't silently
return None for live payment methods.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from app.core.config import settings
from app.core.constants import PaymentMethod
from app.shared.payments import get_payment_provider
from app.shared.payments.ecomtrade24 import EcomTrade24Provider


class TestRegistry:
    def test_card_ecomtrade24_returns_provider(self):
        provider = get_payment_provider(PaymentMethod.CARD_ECOMTRADE24)
        assert provider is not None
        assert isinstance(provider, EcomTrade24Provider)

    def test_card_ecomtrade24_via_string_value(self):
        # Webhook handlers receive the wire string, not the enum.
        assert get_payment_provider("card_ecomtrade24") is not None

    def test_wallet_only_methods_return_none(self):
        # Paypal / USDT have no hosted-checkout adapter; expected None.
        assert get_payment_provider(PaymentMethod.PAYPAL) is None
        assert get_payment_provider(PaymentMethod.USDT_TRC20) is None

    def test_unknown_method_returns_none(self):
        assert get_payment_provider("not-a-real-method") is None


class TestEcomTrade24Signature:
    @pytest.fixture
    def provider(self, monkeypatch):
        monkeypatch.setattr(settings, "ECOMTRADE24_WEBHOOK_SECRET", "test-secret")
        return EcomTrade24Provider()

    @staticmethod
    def _sign(secret: str, body: bytes) -> str:
        return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def test_valid_signature_accepted(self, provider):
        body = b'{"event_id":"abc","event_type":"payment.succeeded"}'
        sig = self._sign("test-secret", body)
        assert provider.verify_webhook_signature(body, sig) is True

    def test_tampered_body_rejected(self, provider):
        body = b'{"event_id":"abc"}'
        sig = self._sign("test-secret", body)
        # Same signature, different body -> reject.
        assert provider.verify_webhook_signature(b'{"event_id":"forged"}', sig) is False

    def test_wrong_secret_rejected(self, provider):
        body = b"payload"
        bad_sig = self._sign("attacker-guess", body)
        assert provider.verify_webhook_signature(body, bad_sig) is False

    def test_missing_signature_rejected(self, provider):
        assert provider.verify_webhook_signature(b"payload", "") is False

    def test_unconfigured_secret_rejects_everything(self, monkeypatch):
        monkeypatch.setattr(settings, "ECOMTRADE24_WEBHOOK_SECRET", "")
        provider = EcomTrade24Provider()
        body = b"payload"
        any_sig = self._sign("anything", body)
        # Defence in depth: secret unset means we don't trust *any* webhook.
        assert provider.verify_webhook_signature(body, any_sig) is False
