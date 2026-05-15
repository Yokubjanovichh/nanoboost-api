"""payment infrastructure — provider columns + webhook idempotency

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-09 14:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres ENUM ADD VALUE must run outside a transaction in older
    # versions. Alembic wraps the migration in one — autocommit_block() opens
    # a sub-block that commits before continuing, so the new value becomes
    # visible to subsequent statements in the same migration.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE payment_method ADD VALUE IF NOT EXISTS 'card_ecomtrade24'"
        )

    # --- orders payment columns ---
    op.add_column(
        "orders",
        sa.Column("payment_provider", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("payment_session_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("payment_checkout_url", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column(
            "payment_status_updated_at", sa.DateTime(timezone=True), nullable=True
        ),
    )

    # --- payment_webhook_events ---
    op.create_table(
        "payment_webhook_events",
        sa.Column("provider", sa.String(length=50), primary_key=True, nullable=False),
        sa.Column("event_id", sa.String(length=200), primary_key=True, nullable=False),
        sa.Column(
            "order_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_payment_webhook_events_order_id",
        "payment_webhook_events",
        ["order_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payment_webhook_events_order_id",
        table_name="payment_webhook_events",
    )
    op.drop_table("payment_webhook_events")

    op.drop_column("orders", "payment_status_updated_at")
    op.drop_column("orders", "payment_checkout_url")
    op.drop_column("orders", "payment_session_id")
    op.drop_column("orders", "payment_provider")

    # Postgres ENUM value drop is intentionally skipped — DROP VALUE is not
    # supported pre-PG 17 and dropping the value while orders still reference
    # it would corrupt data. The unused enum member is harmless.
