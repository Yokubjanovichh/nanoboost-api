"""orders.final_total_eur: snapshot EUR total at order creation

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-21 10:00:00

Nullable on purpose: pre-existing rows never had this column. Application
code populates it for every new order from 0011 onwards; admin reporting
falls back to per-item aggregation only for the legacy NULLs.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("final_total_eur", sa.Numeric(10, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "final_total_eur")
