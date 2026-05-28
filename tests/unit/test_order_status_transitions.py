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
            # Pre-fulfilment
            (OrderStatus.PENDING, OrderStatus.PAID),
            (OrderStatus.PENDING, OrderStatus.CANCELLED),
            # Fulfilment pipeline (paid → awaiting_booster → in_progress
            # → booster_completed → delivered_to_client → completed)
            (OrderStatus.PAID, OrderStatus.AWAITING_BOOSTER),
            (OrderStatus.PAID, OrderStatus.CANCELLED),
            (OrderStatus.PAID, OrderStatus.REFUNDED),
            (OrderStatus.AWAITING_BOOSTER, OrderStatus.IN_PROGRESS),
            (OrderStatus.AWAITING_BOOSTER, OrderStatus.CANCELLED),
            (OrderStatus.AWAITING_BOOSTER, OrderStatus.REFUNDED),
            (OrderStatus.IN_PROGRESS, OrderStatus.BOOSTER_COMPLETED),
            (OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED),
            (OrderStatus.IN_PROGRESS, OrderStatus.REFUNDED),
            (OrderStatus.BOOSTER_COMPLETED, OrderStatus.DELIVERED_TO_CLIENT),
            (OrderStatus.BOOSTER_COMPLETED, OrderStatus.CANCELLED),
            (OrderStatus.BOOSTER_COMPLETED, OrderStatus.REFUNDED),
            (OrderStatus.DELIVERED_TO_CLIENT, OrderStatus.COMPLETED),
            (OrderStatus.DELIVERED_TO_CLIENT, OrderStatus.REFUNDED),
            (OrderStatus.COMPLETED, OrderStatus.REFUNDED),
        ],
    )
    def test_allowed(self, current, target):
        # No raise = passes.
        assert_transition(current, target)

    @pytest.mark.parametrize(
        "current,target",
        [
            # Cannot skip a stage in the pipeline
            (OrderStatus.PENDING, OrderStatus.IN_PROGRESS),
            (OrderStatus.PENDING, OrderStatus.COMPLETED),
            (OrderStatus.PENDING, OrderStatus.AWAITING_BOOSTER),
            (OrderStatus.PENDING, OrderStatus.BOOSTER_COMPLETED),
            (OrderStatus.PAID, OrderStatus.IN_PROGRESS),  # must go via AWAITING_BOOSTER
            (OrderStatus.PAID, OrderStatus.BOOSTER_COMPLETED),
            (OrderStatus.PAID, OrderStatus.DELIVERED_TO_CLIENT),
            (OrderStatus.PAID, OrderStatus.COMPLETED),
            (OrderStatus.AWAITING_BOOSTER, OrderStatus.BOOSTER_COMPLETED),  # skip IN_PROGRESS
            (OrderStatus.AWAITING_BOOSTER, OrderStatus.COMPLETED),
            (OrderStatus.IN_PROGRESS, OrderStatus.DELIVERED_TO_CLIENT),  # skip BOOSTER_COMPLETED
            (OrderStatus.IN_PROGRESS, OrderStatus.COMPLETED),
            (OrderStatus.BOOSTER_COMPLETED, OrderStatus.COMPLETED),  # skip DELIVERED_TO_CLIENT
            # Cannot rewind
            (OrderStatus.AWAITING_BOOSTER, OrderStatus.PAID),
            (OrderStatus.IN_PROGRESS, OrderStatus.AWAITING_BOOSTER),
            (OrderStatus.BOOSTER_COMPLETED, OrderStatus.IN_PROGRESS),
            (OrderStatus.DELIVERED_TO_CLIENT, OrderStatus.BOOSTER_COMPLETED),
            # Cancel disallowed once delivered to the client.
            (OrderStatus.DELIVERED_TO_CLIENT, OrderStatus.CANCELLED),
            (OrderStatus.COMPLETED, OrderStatus.PENDING),
            (OrderStatus.COMPLETED, OrderStatus.CANCELLED),
            # Terminal -> anything is rejected
            (OrderStatus.CANCELLED, OrderStatus.PAID),
            (OrderStatus.CANCELLED, OrderStatus.REFUNDED),
            (OrderStatus.REFUNDED, OrderStatus.PENDING),
            (OrderStatus.REFUNDED, OrderStatus.PAID),
        ],
    )
    def test_rejected(self, current, target):
        with pytest.raises(InvalidStatusTransitionError):
            assert_transition(current, target)

    @pytest.mark.parametrize(
        "status",
        list(OrderStatus),
    )
    def test_self_transition_rejected(self, status):
        with pytest.raises(ValidationFailureError):
            assert_transition(status, status)
