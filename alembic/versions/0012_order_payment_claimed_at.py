"""orders.payment_claimed_at: manual-payment "I have paid" timestamp

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-21 14:00:00

Set by the customer-facing claim endpoint for PayPal / USDT orders.
Status stays PENDING until the admin verifies the wallet/PayPal balance
and flips it to PAID, at which point `paid_at` is set as usual.
Nullable — hosted-checkout providers (e.g. EcomTrade24) never touch it.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("payment_claimed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "payment_claimed_at")
