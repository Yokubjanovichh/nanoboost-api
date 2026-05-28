"""Russian labels for OrderStatus values used in Telegram/email
notifications must match the admin-UI copy (single source of truth).
Missing entries fall back to the raw enum value and leak English to
the operator inbox."""

from __future__ import annotations

import pytest

from app.core.constants import OrderStatus
from app.shared.notifications.orders import STATUS_LABEL_RU


@pytest.mark.parametrize(
    "status,expected",
    [
        (OrderStatus.AWAITING_BOOSTER, "Ожидает бустера"),
        (OrderStatus.BOOSTER_COMPLETED, "Выполнен бустером"),
        (OrderStatus.DELIVERED_TO_CLIENT, "Выдан клиенту"),
    ],
)
def test_pipeline_statuses_have_russian_labels(status, expected):
    assert STATUS_LABEL_RU[status] == expected


def test_every_order_status_has_a_label():
    # Guards against forgetting to extend the map when a new status is
    # added — render would silently fall back to str(status).
    missing = [s for s in OrderStatus if s not in STATUS_LABEL_RU]
    assert not missing, f"OrderStatus values missing from STATUS_LABEL_RU: {missing}"
