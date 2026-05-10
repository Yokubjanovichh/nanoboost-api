"""Phase 4 schema alignment: rename order/order_item columns,
add service_snapshot JSONB, total_price_eur, clients.whatsapp.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-08 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- orders ---
    op.alter_column("orders", "discount_usd", new_column_name="discount_amount_usd")

    # --- order_items: simple renames ---
    op.alter_column("order_items", "qty", new_column_name="quantity")
    op.alter_column(
        "order_items", "price_usd_at_order", new_column_name="unit_price_usd"
    )
    op.alter_column(
        "order_items", "price_eur_at_order", new_column_name="unit_price_eur"
    )
    op.alter_column(
        "order_items", "line_total_usd", new_column_name="total_price_usd"
    )

    # --- order_items: total_price_eur (new column, backfill) ---
    op.add_column(
        "order_items",
        sa.Column(
            "total_price_eur",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
            server_default="0",
        ),
    )
    op.execute(
        """
        UPDATE order_items
           SET total_price_eur = (unit_price_eur * quantity)::numeric(10, 2)
        """
    )
    # Drop the temporary default; future inserts must supply a value.
    op.alter_column("order_items", "total_price_eur", server_default=None)

    # --- order_items: option_id (loose link to service_options) ---
    op.add_column(
        "order_items",
        sa.Column("option_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_order_items_option_id",
        "order_items",
        "service_options",
        ["option_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- order_items: service_snapshot JSONB ---
    op.add_column(
        "order_items",
        sa.Column(
            "service_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    # Backfill from legacy snapshot columns BEFORE dropping them.
    op.execute(
        """
        UPDATE order_items
           SET service_snapshot = jsonb_build_object(
                   'slug',       service_slug,
                   'title',      service_title,
                   'image_url',  NULL,
                   'platform',   NULL,
                   'game_slug',  NULL
               )
        """
    )
    op.alter_column("order_items", "service_snapshot", server_default=None)

    # Snapshot now owns slug/title. Drop the legacy denormalized columns.
    op.drop_column("order_items", "service_title")
    op.drop_column("order_items", "service_slug")

    # --- order_items: total_price_eur non-negativity (paired with USD) ---
    op.create_check_constraint(
        "ck_order_items_total_price_eur_nonneg",
        "order_items",
        "total_price_eur >= 0",
    )

    # --- clients.whatsapp ---
    op.add_column(
        "clients", sa.Column("whatsapp", sa.String(length=50), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("clients", "whatsapp")

    op.drop_constraint(
        "ck_order_items_total_price_eur_nonneg",
        "order_items",
        type_="check",
    )

    # Re-create legacy columns and backfill from snapshot before dropping it.
    op.add_column(
        "order_items",
        sa.Column("service_slug", sa.String(length=150), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("service_title", sa.String(length=300), nullable=True),
    )
    op.execute(
        """
        UPDATE order_items
           SET service_slug  = service_snapshot ->> 'slug',
               service_title = service_snapshot ->> 'title'
        """
    )
    op.alter_column("order_items", "service_slug", nullable=False)
    op.alter_column("order_items", "service_title", nullable=False)

    op.drop_column("order_items", "service_snapshot")

    op.drop_constraint(
        "fk_order_items_option_id", "order_items", type_="foreignkey"
    )
    op.drop_column("order_items", "option_id")
    op.drop_column("order_items", "total_price_eur")

    op.alter_column(
        "order_items", "total_price_usd", new_column_name="line_total_usd"
    )
    op.alter_column(
        "order_items", "unit_price_eur", new_column_name="price_eur_at_order"
    )
    op.alter_column(
        "order_items", "unit_price_usd", new_column_name="price_usd_at_order"
    )
    op.alter_column("order_items", "quantity", new_column_name="qty")

    op.alter_column("orders", "discount_amount_usd", new_column_name="discount_usd")
