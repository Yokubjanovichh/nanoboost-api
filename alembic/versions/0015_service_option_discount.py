"""service option per-row discount fields

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-28 00:30:00

Adds optional, admin-managed per-option discount fields:

  * discount_percent       (1-100, NULL when amount discount or no discount)
  * discount_amount_usd    (>0,    paired with discount_amount_eur)
  * discount_amount_eur    (>0,    paired with discount_amount_usd)

Application invariants (enforced by the schema layer, not the DB):
  - percent and amount_* are mutually exclusive
  - amount_usd and amount_eur are paired (either both NULL or both set)

USDT-TRC20's 5% order-level discount stacks naturally because it is
applied to the subtotal *after* item-level discounts.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "service_options",
        sa.Column("discount_percent", sa.Integer(), nullable=True),
    )
    op.add_column(
        "service_options",
        sa.Column("discount_amount_usd", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "service_options",
        sa.Column("discount_amount_eur", sa.Numeric(10, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("service_options", "discount_amount_eur")
    op.drop_column("service_options", "discount_amount_usd")
    op.drop_column("service_options", "discount_percent")
