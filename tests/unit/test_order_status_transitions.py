"""assert_transition is the single source of truth for legal order-state
flow; bugs here translate directly into corrupt admin data."""

from __future__ import annotations

import pytest

from app.core.constants import OrderStatus
from app.core.exceptions import (
    InvalidStatusTransitionError,
    ValidationFailureError,
)
from app.features.orders.service import assert_transition


class TestTransitions:
    @pytest.mark.parametrize(
        "current,target",
        [
            (OrderStatus.PENDING, OrderStatus.PAID),
            (OrderStatus.PENDING, OrderStatus.CANCELLED),
            (OrderStatus.PAID, OrderStatus.IN_PROGRESS),
            (OrderStatus.PAID, OrderStatus.REFUNDED),
            (OrderStatus.IN_PROGRESS, OrderStatus.COMPLETED),
            (OrderStatus.COMPLETED, OrderStatus.REFUNDED),
        ],
    )
    def test_allowed(self, current, target):
        # No raise = passes.
        assert_transition(current, target)

    @pytest.mark.parametrize(
        "current,target",
        [
            (OrderStatus.PENDING, OrderStatus.IN_PROGRESS),  # skip PAID
            (OrderStatus.PENDING, OrderStatus.COMPLETED),  # skip everything
            (OrderStatus.CANCELLED, OrderStatus.PAID),  # terminal -> any
            (OrderStatus.REFUNDED, OrderStatus.PENDING),  # terminal -> any
            (OrderStatus.COMPLETED, OrderStatus.PENDING),  # rewind
        ],
    )
    def test_rejected(self, current, target):
        with pytest.raises(InvalidStatusTransitionError):
            assert_transition(current, target)

    def test_self_transition_rejected(self):
        with pytest.raises(ValidationFailureError):
            assert_transition(OrderStatus.PAID, OrderStatus.PAID)
