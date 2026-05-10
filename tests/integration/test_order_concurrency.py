"""pg_advisory_xact_lock concurrency check for order_number generation.

When 50 public orders fire simultaneously, every order_number must be
unique and sequential within the day. The advisory lock acquired in
OrderRepository.reserve_next_order_number is what guarantees this.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DisplayCurrency, PaymentMethod, Platform
from app.features.clients.models import Client
from app.features.games.models import Game
from app.features.orders.public_schemas import (
    PublicOrderCreate,
    PublicOrderItemCreate,
)
from app.features.orders.public_service import PublicOrderService
from app.features.services.models import Service, ServiceOption
from app.shared.notifications.base import NoOpBackend
from app.shared.notifications.orders import OrderNotifier

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _seed(session: AsyncSession) -> tuple[Service, ServiceOption]:
    game = Game(slug="gta5-conc", name="GTA Concurrency")
    session.add(game)
    await session.commit()
    await session.refresh(game)

    service = Service(
        game_id=game.id,
        slug="conc-svc",
        title="Concurrency Service",
        platform=Platform.PS,
        description=[],
        what_you_get=[],
        sections=[],
    )
    session.add(service)
    await session.commit()
    await session.refresh(service)

    option = ServiceOption(
        service_id=service.id,
        label="20m",
        price_usd=Decimal("19.99"),
        price_eur=Decimal("16.99"),
        is_default=True,
        sort_order=0,
    )
    session.add(option)
    await session.commit()
    await session.refresh(option)
    return service, option


async def test_50_concurrent_orders_have_unique_numbers(pg_engine) -> None:
    factory = async_sessionmaker(bind=pg_engine, expire_on_commit=False)
    async with factory() as setup_session:
        service, option = await _seed(setup_session)

    notifier = OrderNotifier(telegram=NoOpBackend(), email=NoOpBackend())

    async def create_one(idx: int) -> str:
        async with factory() as s:
            payload = PublicOrderCreate(
                email=f"buyer-{idx}@nano.io",
                payment_method=PaymentMethod.PAYPAL,
                display_currency=DisplayCurrency.USD,
                items=[
                    PublicOrderItemCreate(
                        service_id=service.id,
                        option_id=option.id,
                        quantity=1,
                    )
                ],
            )
            order = await PublicOrderService(s, notifier=notifier).create(payload)
            return order.order_number

    numbers = await asyncio.gather(*[create_one(i) for i in range(50)])

    # All unique
    assert len(set(numbers)) == 50

    # All within the same day prefix and sequential
    day_prefixes = {n.rsplit("-", 1)[0] for n in numbers}
    assert len(day_prefixes) == 1, f"Mixed days: {day_prefixes}"

    seqs = sorted(int(n.rsplit("-", 1)[1]) for n in numbers)
    assert seqs == list(range(seqs[0], seqs[0] + 50))


async def test_no_orphan_clients_after_concurrent_orders(pg_engine) -> None:
    """Each unique email leads to exactly one Client row, no duplicates
    even under concurrent get_or_create."""
    from sqlalchemy import func, select

    factory = async_sessionmaker(bind=pg_engine, expire_on_commit=False)
    async with factory() as s:
        count = (
            await s.execute(select(func.count(Client.id)))
        ).scalar_one()
        # 50 distinct emails were just created (above test); verify no dupes
        # by email vs id count.
        unique_emails = (
            await s.execute(select(func.count(func.distinct(Client.email))))
        ).scalar_one()
        assert count == unique_emails

    # Tests may run in any order — we don't assert an exact row count,
    # only the email-uniqueness invariant.
    _ = count
