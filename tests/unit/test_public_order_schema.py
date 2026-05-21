"""Schema-level validation for the public order checkout payload.

Covers the FAZA 4 surface: WhatsApp normalization (E.164-friendly input,
stored as `+<digits>`) and the response shape carrying EUR/discount.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.features.orders.public_schemas import PublicOrderCreate, PublicOrderResponse


def _make_payload(**overrides):
    base = {
        "email": "buyer@example.com",
        "payment_method": "card_ecomtrade24",
        "display_currency": "USD",
        "items": [{"service_id": str(uuid4()), "option_id": str(uuid4()), "quantity": 1}],
    }
    base.update(overrides)
    return base


# --- WhatsApp validator ---------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+1 555 123 4567", "+15551234567"),
        ("+998-90-123-45-67", "+998901234567"),
        ("  +44 7700 900123  ", "+447700900123"),
        # No leading + → still accepted, stored digits-only.
        ("5551234567", "5551234567"),
        # Empty/whitespace normalize to None — same as omitting the field.
        ("", None),
        ("   ", None),
    ],
)
def test_whatsapp_normalizes_to_e164_digits(raw, expected):
    payload = PublicOrderCreate(**_make_payload(whatsapp=raw))
    assert payload.whatsapp == expected


@pytest.mark.parametrize(
    "bad",
    [
        "abc123",  # letters
        "+12",  # too short (<7)
        "+" + "9" * 60,  # too long (>50)
        "+1 (555) 123-4567",  # parentheses not in the allowed set
        "++1234567",  # double plus
    ],
)
def test_whatsapp_rejects_garbage(bad):
    with pytest.raises(ValidationError):
        PublicOrderCreate(**_make_payload(whatsapp=bad))


def test_whatsapp_optional_when_omitted():
    payload = PublicOrderCreate(**_make_payload())
    assert payload.whatsapp is None


# --- Response shape -------------------------------------------------------


def test_response_shape_allows_eur_and_discount_nulls():
    """Legacy orders (created before migration 0011) have NULL EUR — the
    response must still serialise cleanly with the fields explicit."""
    resp = PublicOrderResponse(
        order_number="NB-20260521-1001",
        status="pending",
        final_total_usd=10.0,
        final_total_eur=None,
        discount_amount_usd=None,
        display_currency="USD",
        created_at="2026-05-21T10:00:00Z",
    )
    dumped = resp.model_dump()
    assert dumped["final_total_eur"] is None
    assert dumped["discount_amount_usd"] is None
    assert dumped["checkout_url"] is None


def test_response_shape_carries_eur_and_discount():
    resp = PublicOrderResponse(
        order_number="NB-20260521-1002",
        status="pending",
        final_total_usd=95.0,
        final_total_eur=85.5,
        discount_amount_usd=5.0,
        display_currency="EUR",
        created_at="2026-05-21T10:00:00Z",
        checkout_url="https://gw.example/checkout/abc",
    )
    dumped = resp.model_dump()
    assert dumped["final_total_eur"] == 85.5
    assert dumped["discount_amount_usd"] == 5.0
    assert dumped["display_currency"].value == "EUR"
