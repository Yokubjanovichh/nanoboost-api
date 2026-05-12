"""create clients, orders, order_items tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-07 00:03:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ENUM types — using create_type=False to avoid duplicate-create on column.
    order_status = postgresql.ENUM(
        "pending",
        "paid",
        "in_progress",
        "completed",
        "cancelled",
        "refunded",
        name="order_status",
        create_type=False,
    )
    order_status.create(op.get_bind(), checkfirst=True)

    payment_method = postgresql.ENUM(
        "paypal",
        "usdt_trc20",
        name="payment_method",
        create_type=False,
    )
    payment_method.create(op.get_bind(), checkfirst=True)

    display_currency = postgresql.ENUM(
        "USD",
        "EUR",
        name="display_currency",
        create_type=False,
    )
    display_currency.create(op.get_bind(), checkfirst=True)

    # --- clients ---
    op.create_table(
        "clients",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("discord", sa.String(length=255), nullable=True),
        sa.Column("telegram", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="uq_clients_email"),
    )
    op.create_index("ix_clients_email", "clients", ["email"])

    # --- orders ---
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("order_number", sa.String(length=32), nullable=False),
        sa.Column(
            "client_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", order_status, nullable=False, server_default="pending"),
        sa.Column("payment_method", payment_method, nullable=False),
        sa.Column("display_currency", display_currency, nullable=False, server_default="USD"),
        sa.Column("subtotal_usd", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "discount_usd",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column("discount_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("final_total_usd", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("order_number", name="uq_orders_order_number"),
        sa.CheckConstraint("subtotal_usd >= 0", name="ck_orders_subtotal_nonneg"),
        sa.CheckConstraint("final_total_usd >= 0", name="ck_orders_final_total_nonneg"),
        sa.CheckConstraint(
            "discount_percent >= 0 AND discount_percent <= 100",
            name="ck_orders_discount_percent_range",
        ),
    )
    op.create_index("ix_orders_order_number", "orders", ["order_number"])
    op.create_index("ix_orders_client_id", "orders", ["client_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_created_at", "orders", ["created_at"])

    # --- order_items ---
    op.create_table(
        "order_items",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "order_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "service_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("services.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("service_slug", sa.String(length=150), nullable=False),
        sa.Column("service_title", sa.String(length=300), nullable=False),
        sa.Column("option_label", sa.String(length=200), nullable=True),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "price_usd_at_order",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
        ),
        sa.Column(
            "price_eur_at_order",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
        ),
        sa.Column("line_total_usd", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("qty > 0", name="ck_order_items_qty_positive"),
        sa.CheckConstraint("price_usd_at_order >= 0", name="ck_order_items_price_usd_nonneg"),
        sa.CheckConstraint("price_eur_at_order >= 0", name="ck_order_items_price_eur_nonneg"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_table("order_items")

    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_client_id", table_name="orders")
    op.drop_index("ix_orders_order_number", table_name="orders")
    op.drop_table("orders")

    op.drop_index("ix_clients_email", table_name="clients")
    op.drop_table("clients")

    sa.Enum(name="display_currency").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="payment_method").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="order_status").drop(op.get_bind(), checkfirst=True)
