"""calculate_discounted_price is the pricing primitive shared by the
public services API and order creation. A drift here silently mis-charges
real customers, so we cover edge cases (zero-out, rounding, currency
disambiguation, missing fields) before exposing it."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.features.services.schemas import (
    _validate_discount_combination,
    calculate_discounted_price,
)


@dataclass
class _Option:
    price_usd: Decimal
    price_eur: Decimal
    discount_percent: Decimal | None = None
    discount_amount_usd: Decimal | None = None
    discount_amount_eur: Decimal | None = None


def _opt(**kwargs) -> _Option:
    base = {"price_usd": Decimal("100"), "price_eur": Decimal("90")}
    base.update(kwargs)
    return _Option(**base)


class TestCalculateDiscountedPrice:
    def test_no_discount_returns_original(self):
        opt = _opt()
        assert calculate_discounted_price(opt, "USD") == Decimal("100.00")
        assert calculate_discounted_price(opt, "EUR") == Decimal("90.00")

    def test_percent_discount_applies_to_both_currencies(self):
        opt = _opt(discount_percent=10)
        assert calculate_discounted_price(opt, "USD") == Decimal("90.00")
        assert calculate_discounted_price(opt, "EUR") == Decimal("81.00")

    def test_percent_100_zeroes_price(self):
        opt = _opt(discount_percent=100)
        assert calculate_discounted_price(opt, "USD") == Decimal("0.00")
        assert calculate_discounted_price(opt, "EUR") == Decimal("0.00")

    def test_percent_1_is_smallest_meaningful_discount(self):
        opt = _opt(discount_percent=1)
        assert calculate_discounted_price(opt, "USD") == Decimal("99.00")

    def test_amount_discount_applies_per_currency(self):
        # Each currency gets its own absolute amount — provider sets both
        # independently so EUR isn't auto-derived from USD.
        opt = _opt(
            discount_amount_usd=Decimal("15"),
            discount_amount_eur=Decimal("13"),
        )
        assert calculate_discounted_price(opt, "USD") == Decimal("85.00")
        assert calculate_discounted_price(opt, "EUR") == Decimal("77.00")

    def test_amount_discount_floors_at_zero(self):
        # Edge: admin set a discount larger than the price. We refuse to
        # return a negative price — the customer gets 0, never refunded.
        opt = _opt(
            discount_amount_usd=Decimal("150"),
            discount_amount_eur=Decimal("200"),
        )
        assert calculate_discounted_price(opt, "USD") == Decimal("0.00")
        assert calculate_discounted_price(opt, "EUR") == Decimal("0.00")

    def test_percent_wins_when_both_set_defensively(self):
        # Schema rejects this combination, but DB rows are liberal — the
        # helper must still produce a deterministic price.
        opt = _opt(
            discount_percent=20,
            discount_amount_usd=Decimal("5"),
            discount_amount_eur=Decimal("5"),
        )
        assert calculate_discounted_price(opt, "USD") == Decimal("80.00")
        assert calculate_discounted_price(opt, "EUR") == Decimal("72.00")

    def test_rounds_to_two_decimals(self):
        # Round-trip through quantize: 33% off 100 USD = 67.00; same
        # 33% off 90 EUR = 60.30 (rounds cleanly, no banker's edge case).
        opt = _opt(discount_percent=33)
        assert calculate_discounted_price(opt, "USD") == Decimal("67.00")
        assert calculate_discounted_price(opt, "EUR") == Decimal("60.30")

    def test_unsupported_currency_raises(self):
        opt = _opt()
        with pytest.raises(ValueError, match="Unsupported currency"):
            calculate_discounted_price(opt, "GBP")

    def test_currency_is_case_insensitive(self):
        opt = _opt(discount_percent=10)
        assert calculate_discounted_price(opt, "usd") == Decimal("90.00")
        assert calculate_discounted_price(opt, "eur") == Decimal("81.00")

    # --- Decimal precision (migration 0016) -------------------------------

    def test_fractional_percent_keeps_three_decimal_precision(self):
        # 100 * (100 - 50.003) / 100 = 49.997 -> quantize to 50.00
        # (50.003% chops 50.003 dollars, leaving 49.997 — round-half-even
        # to two decimal places rounds the 7 up to 50.00).
        opt = _opt(discount_percent=Decimal("50.003"))
        assert calculate_discounted_price(opt, "USD") == Decimal("50.00")

    def test_near_100_percent_floors_at_cents(self):
        # 99.999% off 100 = 100 * 0.00001 = 0.001 -> quantize -> 0.00.
        opt = _opt(discount_percent=Decimal("99.999"))
        assert calculate_discounted_price(opt, "USD") == Decimal("0.00")

    def test_tiny_decimal_percent_is_a_no_op_after_quantize(self):
        # 0.001% off 64.99 = 64.98935065... -> quantize -> 64.99.
        opt = _opt(
            price_usd=Decimal("64.99"),
            price_eur=Decimal("60"),
            discount_percent=Decimal("0.001"),
        )
        assert calculate_discounted_price(opt, "USD") == Decimal("64.99")

    def test_legacy_int_value_matches_decimal_equivalent(self):
        # Migration 0016 backward-compat: rows holding 10 (legacy int)
        # must price identically to rows holding Decimal("10.000").
        int_opt = _opt(price_usd=Decimal("64.99"), discount_percent=10)
        dec_opt = _opt(price_usd=Decimal("64.99"), discount_percent=Decimal("10.000"))
        assert calculate_discounted_price(int_opt, "USD") == calculate_discounted_price(
            dec_opt, "USD"
        )
        # Spot value: 64.99 * 0.90 = 58.491 -> quantize -> 58.49.
        assert calculate_discounted_price(int_opt, "USD") == Decimal("58.49")


class TestValidateDiscountCombination:
    def test_all_null_is_allowed(self):
        _validate_discount_combination(None, None, None)

    def test_percent_only_allowed(self):
        _validate_discount_combination(15, None, None)

    def test_amount_pair_allowed(self):
        _validate_discount_combination(None, Decimal("5"), Decimal("4"))

    @pytest.mark.parametrize(
        "p",
        [
            0,
            Decimal("0"),
            Decimal("0.000"),
            -1,
            Decimal("-0.001"),
            100,
            Decimal("100"),
            Decimal("100.001"),
            101,
            200,
        ],
    )
    def test_percent_out_of_range_rejected(self, p):
        # Migration 0016: range is strictly between 0 and 100 (exclusive).
        with pytest.raises(ValueError, match="strictly between 0 and 100"):
            _validate_discount_combination(p, None, None)

    @pytest.mark.parametrize(
        "p",
        [
            Decimal("0.001"),
            Decimal("0.5"),
            Decimal("1"),
            Decimal("12.5"),
            Decimal("50.003"),
            Decimal("99.999"),
            10,  # legacy int still valid
        ],
    )
    def test_percent_in_range_accepted(self, p):
        _validate_discount_combination(p, None, None)

    def test_percent_and_amount_combination_rejected(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            _validate_discount_combination(10, Decimal("1"), Decimal("1"))

    def test_amount_usd_without_eur_rejected(self):
        with pytest.raises(ValueError, match="provided together"):
            _validate_discount_combination(None, Decimal("5"), None)

    def test_amount_eur_without_usd_rejected(self):
        with pytest.raises(ValueError, match="provided together"):
            _validate_discount_combination(None, None, Decimal("5"))

    @pytest.mark.parametrize("v", [Decimal("0"), Decimal("-1")])
    def test_non_positive_amount_rejected(self, v):
        with pytest.raises(ValueError, match="greater than 0"):
            _validate_discount_combination(None, v, Decimal("1"))
