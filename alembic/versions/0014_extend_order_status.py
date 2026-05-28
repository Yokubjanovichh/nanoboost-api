"""extend order_status enum + intermediate stage timestamps

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-28 00:00:00

Adds three intermediate fulfilment stages between PAID and COMPLETED so the
admin pipeline can model the boost lifecycle without overloading IN_PROGRESS:
  paid -> awaiting_booster -> in_progress -> booster_completed
       -> delivered_to_client -> completed

Each new stage gets a dedicated nullable timestamp column on the orders
table; the application sets it from the change_status path.

Downgrade drops the three new columns. The ENUM values are intentionally
retained — Postgres pre-17 lacks DROP VALUE and dropping while orders may
still reference the value would corrupt data. Same convention as 0008.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ENUM extension must run outside the surrounding migration transaction
    # (Postgres pre-17 restriction). autocommit_block commits before
    # continuing, so subsequent SQL in this migration sees the new values.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE order_status ADD VALUE IF NOT EXISTS 'awaiting_booster'")
        op.execute("ALTER TYPE order_status ADD VALUE IF NOT EXISTS 'booster_completed'")
        op.execute("ALTER TYPE order_status ADD VALUE IF NOT EXISTS 'delivered_to_client'")

    op.add_column(
        "orders",
        sa.Column("awaiting_booster_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("booster_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("delivered_to_client_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "delivered_to_client_at")
    op.drop_column("orders", "booster_completed_at")
    op.drop_column("orders", "awaiting_booster_at")
    # ENUM values intentionally retained (see module docstring).
