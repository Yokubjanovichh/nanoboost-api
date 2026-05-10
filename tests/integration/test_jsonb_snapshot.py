"""service_snapshot stored as JSONB and queryable via Postgres operators.

The Phase 5 0005 migration introduced order_items.service_snapshot JSONB
backfilled from the old service_slug/service_title columns. This test
exercises the cross-dialect with_variant(JSONB, "postgresql") wiring.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.constants import DisplayCurrency, OrderStatus, PaymentMethod
from app.features.clients.models import Client
from app.features.orders.models import Order, OrderItem

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_service_snapshot_is_queryable_via_jsonb_operators(
    pg_session,
) -> None:
    client = Client(email="snap@nano.io")
    pg_session.add(client)
    await pg_session.commit()
    await pg_session.refresh(client)

    order = Order(
        order_number="NB-99990509-9001",
        client_id=client.id,
        status=OrderStatus.PENDING,
        payment_method=PaymentMethod.PAYPAL,
        display_currency=DisplayCurrency.USD,
        subtotal_usd=Decimal("19.99"),
        discount_amount_usd=Decimal("0"),
        discount_percent=0,
        final_total_usd=Decimal("19.99"),
    )
    snapshot = {
        "slug": "gta-cash-ps",
        "title": "GTA Cash Boost",
        "image_url": "/uploads/services/x.webp",
        "platform": "ps",
        "game_slug": "gta5",
    }
    order.items.append(
        OrderItem(
            service_snapshot=snapshot,
            option_label="20 million",
            quantity=1,
            unit_price_usd=Decimal("19.99"),
            unit_price_eur=Decimal("16.99"),
            total_price_usd=Decimal("19.99"),
            total_price_eur=Decimal("16.99"),
        )
    )
    pg_session.add(order)
    await pg_session.commit()

    # Query via JSONB ->> operator (text extraction)
    row = (
        await pg_session.execute(
            text(
                "SELECT service_snapshot ->> 'slug' AS slug, "
                "service_snapshot ->> 'platform' AS platform "
                "FROM order_items WHERE order_id = :order_id"
            ),
            {"order_id": str(order.id)},
        )
    ).one()
    assert row.slug == "gta-cash-ps"
    assert row.platform == "ps"

    # Confirm all 5 keys are present and accessible
    keys_row = (
        await pg_session.execute(
            text(
                "SELECT jsonb_object_keys(service_snapshot) AS k "
                "FROM order_items WHERE order_id = :order_id ORDER BY k"
            ),
            {"order_id": str(order.id)},
        )
    ).all()
    keys = {row.k for row in keys_row}
    assert keys == {"slug", "title", "image_url", "platform", "game_slug"}
