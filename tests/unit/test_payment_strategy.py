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


class TestEcomTrade24ParseWebhookEvent:
    """Fixture sample is the exact JSON the provider sent on 2026-05-23
    (test webhook from dashboard). Real-payment shape only differs in
    populated `txid` / non-zero `session_id` / terminal `status`."""

    SAMPLE_TEST_WEBHOOK = {
        "event": "payment.session",
        "session_id": 0,
        "order_id": "TEST-WEBHOOK-7FE876BC42",
        "status": "test",
        "amount": "0.00",
        "currency": "USD",
        "email": None,
        "txid": None,
        "merchant_id": 175,
        "shop_domain": "nanoboost.io",
        "sent_at": "2026-05-23T16:43:11+00:00",
        "provider": "ecomtrade24",
        "test": True,
    }

    @pytest.fixture
    def provider(self):
        return EcomTrade24Provider()

    def test_test_webhook_parses_without_error(self, provider):
        event = provider.parse_webhook_event(self.SAMPLE_TEST_WEBHOOK)
        assert event.event_type == "payment.session"
        assert event.event_id == "0:test"
        assert event.order_id == "TEST-WEBHOOK-7FE876BC42"
        assert event.status == "pending"  # "test" normalises to no-op

    def test_paid_status_normalises_to_paid(self, provider):
        payload = {**self.SAMPLE_TEST_WEBHOOK, "session_id": 6420, "status": "paid"}
        event = provider.parse_webhook_event(payload)
        assert event.event_id == "6420:paid"
        assert event.status == "paid"

    def test_event_id_idempotent_across_retries(self, provider):
        """Same session + same status → same event_id so the (provider,
        event_id) PK dedupes provider retries naturally."""
        a = provider.parse_webhook_event({**self.SAMPLE_TEST_WEBHOOK, "session_id": 6420, "status": "paid"})
        b = provider.parse_webhook_event({**self.SAMPLE_TEST_WEBHOOK, "session_id": 6420, "status": "paid"})
        assert a.event_id == b.event_id

    def test_status_transition_yields_different_event_id(self, provider):
        """pending → paid is a real transition, not a retry — must produce
        distinct event_ids so both rows land in the audit table."""
        pending = provider.parse_webhook_event({**self.SAMPLE_TEST_WEBHOOK, "session_id": 6420, "status": "pending"})
        paid = provider.parse_webhook_event({**self.SAMPLE_TEST_WEBHOOK, "session_id": 6420, "status": "paid"})
        assert pending.event_id != paid.event_id

    def test_declined_normalises_to_failed(self, provider):
        payload = {**self.SAMPLE_TEST_WEBHOOK, "session_id": 6421, "status": "declined"}
        event = provider.parse_webhook_event(payload)
        assert event.status == "failed"

    def test_missing_event_key_raises(self, provider):
        with pytest.raises(ValueError, match="missing event/session_id"):
            provider.parse_webhook_event({"session_id": 1, "status": "paid"})

    def test_missing_session_id_raises(self, provider):
        with pytest.raises(ValueError, match="missing event/session_id"):
            provider.parse_webhook_event({"event": "payment.session", "status": "paid"})

    def test_raw_payload_preserved_for_audit(self, provider):
        event = provider.parse_webhook_event(self.SAMPLE_TEST_WEBHOOK)
        assert event.raw_payload is self.SAMPLE_TEST_WEBHOOK
