"""service option discount_percent INT -> NUMERIC(7,3)

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-28 00:45:00

Widens discount_percent from whole-number INT to NUMERIC(7,3) so the
admin can target precise campaign rates like 12.5% or 7.499%. Existing
INT values cleanly upcast (10 -> 10.000) — no data rewrite, no app-level
backfill. Computation already runs in Decimal so the helper is untouched.

Downgrade truncates decimals; documented as lossy.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "service_options",
        "discount_percent",
        existing_type=sa.Integer(),
        type_=sa.Numeric(7, 3),
        existing_nullable=True,
        postgresql_using="discount_percent::numeric(7,3)",
    )


def downgrade() -> None:
    # Lossy: 10.500 -> 10, 99.999 -> 99. Acceptable for rollback because
    # truncating one decimal digit is preferable to losing the column.
    op.alter_column(
        "service_options",
        "discount_percent",
        existing_type=sa.Numeric(7, 3),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="discount_percent::integer",
    )
