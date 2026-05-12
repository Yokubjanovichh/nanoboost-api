"""
Test orders + clients seed (real schema bilan).
docker exec nanoboost-api python /app/seed_orders.py
"""

import asyncio
from datetime import datetime, timedelta, timezone, UTC
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.features.clients.models import Client
from app.features.orders.models import Order, OrderItem
from app.features.services.models import Service


CLIENTS = [
    {"email": "john.doe@example.com", "discord": "john_doe#1234", "telegram": None, "notes": None},
    {
        "email": "mary.smith@example.com",
        "discord": None,
        "telegram": "@mary_gamer",
        "notes": "VIP клиент, быстрая доставка",
    },
    {
        "email": "alex.dev@example.com",
        "discord": "alex.dev",
        "telegram": "@alex_dev",
        "notes": None,
    },
]


async def seed():
    now = datetime.now(UTC)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Service))
        services_by_slug = {s.slug: s for s in result.scalars().all()}

        existing = await db.execute(select(Client))
        if existing.scalars().first() is not None:
            print("Clients already exist, skipping seed.")
            return

        clients_by_email = {}
        for c_data in CLIENTS:
            client = Client(id=uuid4(), **c_data)
            db.add(client)
            clients_by_email[c_data["email"]] = client
        await db.flush()
        print(f"OK    {len(clients_by_email)} ta client yaratildi")

        order_specs = [
            {
                "client_email": "john.doe@example.com",
                "order_number": "NB-20260507-1001",
                "status": "pending",
                "payment_method": "paypal",
                "display_currency": "USD",
                "comment": "Срочный заказ, спасибо!",
                "admin_notes": None,
                "created_offset_days": 0,
                "items": [
                    {
                        "service_slug": "gta-cash-cars-ps",
                        "option_label": "20 million",
                        "qty": 1,
                        "usd": 15.99,
                        "eur": 13.99,
                    },
                ],
            },
            {
                "client_email": "mary.smith@example.com",
                "order_number": "NB-20260507-1002",
                "status": "paid",
                "payment_method": "usdt_trc20",
                "display_currency": "USD",
                "comment": None,
                "admin_notes": "Оплата подтверждена в TRC20",
                "created_offset_days": 1,
                "items": [
                    {
                        "service_slug": "gta-cash-ps",
                        "option_label": "30 million",
                        "qty": 1,
                        "usd": 29.99,
                        "eur": 25.99,
                    },
                ],
            },
            {
                "client_email": "john.doe@example.com",
                "order_number": "NB-20260506-1001",
                "status": "in_progress",
                "payment_method": "paypal",
                "display_currency": "EUR",
                "comment": "Пожалуйста, не трогайте мой гараж",
                "admin_notes": "Booster: Mike",
                "created_offset_days": 2,
                "items": [
                    {
                        "service_slug": "gta-level-ps",
                        "option_label": "100 level",
                        "qty": 1,
                        "usd": 49.99,
                        "eur": 42.99,
                    },
                    {
                        "service_slug": "gta-cash-ps",
                        "option_label": "20 million",
                        "qty": 1,
                        "usd": 19.99,
                        "eur": 16.99,
                    },
                ],
            },
            {
                "client_email": "alex.dev@example.com",
                "order_number": "NB-20260505-1001",
                "status": "completed",
                "payment_method": "usdt_trc20",
                "display_currency": "USD",
                "comment": None,
                "admin_notes": "Завершено успешно",
                "created_offset_days": 3,
                "items": [
                    {
                        "service_slug": "gta-modded-xbox",
                        "option_label": "level 120 + 1 Billion",
                        "qty": 1,
                        "usd": 199.99,
                        "eur": 170.99,
                    },
                ],
            },
            {
                "client_email": "alex.dev@example.com",
                "order_number": "NB-20260504-1001",
                "status": "cancelled",
                "payment_method": "paypal",
                "display_currency": "USD",
                "comment": "Передумал, извините",
                "admin_notes": "Возврат не требуется",
                "created_offset_days": 4,
                "items": [
                    {
                        "service_slug": "gta-unlock-pc",
                        "option_label": "Unlock All",
                        "qty": 1,
                        "usd": 29.99,
                        "eur": 25.99,
                    },
                ],
            },
        ]

        for spec in order_specs:
            client = clients_by_email[spec["client_email"]]
            created_at = now - timedelta(days=spec["created_offset_days"])

            subtotal_usd = Decimal("0.00")
            for item in spec["items"]:
                subtotal_usd += Decimal(str(item["usd"])) * item["qty"]

            if spec["payment_method"] == "usdt_trc20":
                discount_percent = 5
                discount_usd = (subtotal_usd * Decimal("0.05")).quantize(Decimal("0.01"))
            else:
                discount_percent = 0
                discount_usd = Decimal("0.00")
            final_total = subtotal_usd - discount_usd

            order_kwargs = {
                "id": uuid4(),
                "order_number": spec["order_number"],
                "client_id": client.id,
                "status": spec["status"],
                "payment_method": spec["payment_method"],
                "display_currency": spec["display_currency"],
                "subtotal_usd": subtotal_usd,
                "discount_percent": discount_percent,
                "discount_usd": discount_usd,
                "final_total_usd": final_total,
                "comment": spec["comment"],
                "admin_notes": spec["admin_notes"],
                "created_at": created_at,
                "updated_at": created_at,
            }
            if spec["status"] == "paid":
                order_kwargs["paid_at"] = created_at
            elif spec["status"] == "in_progress":
                order_kwargs["paid_at"] = created_at
            elif spec["status"] == "completed":
                order_kwargs["paid_at"] = created_at - timedelta(hours=1)
                order_kwargs["completed_at"] = created_at
            elif spec["status"] == "cancelled":
                order_kwargs["cancelled_at"] = created_at

            order = Order(**order_kwargs)
            db.add(order)
            await db.flush()

            for item in spec["items"]:
                service = services_by_slug.get(item["service_slug"])
                if not service:
                    continue
                qty = item["qty"]
                unit_usd = Decimal(str(item["usd"]))
                unit_eur = Decimal(str(item["eur"]))
                order_item = OrderItem(
                    id=uuid4(),
                    order_id=order.id,
                    service_id=service.id,
                    service_slug=service.slug,
                    service_title=service.title,
                    option_label=item["option_label"],
                    qty=qty,
                    price_usd_at_order=unit_usd,
                    price_eur_at_order=unit_eur,
                    line_total_usd=unit_usd * qty,
                    created_at=created_at,
                    updated_at=created_at,
                )
                db.add(order_item)

            print(
                f"OK    order {spec['order_number']} ({spec['status']:<11}) — {len(spec['items'])} item"
            )

        await db.commit()
        print("\nSEED YAKUNLANDI: 3 client, 5 order")


if __name__ == "__main__":
    asyncio.run(seed())
