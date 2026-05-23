"""game_faqs: per-game FAQ entries

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-23 18:00:00

Standalone table — `game_slug` references `games.slug` semantically but
not at the DB level (slugs can be renamed and FAQs may be staged for a
game row that doesn't yet exist). Composite index keeps the public read
path (filter by slug + is_active, sort by order_index) covered.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "game_faqs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("game_slug", sa.String(length=100), nullable=False),
        sa.Column("question", sa.String(length=500), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_game_faqs_slug_active_order",
        "game_faqs",
        ["game_slug", "is_active", "order_index"],
    )


def downgrade() -> None:
    op.drop_index("ix_game_faqs_slug_active_order", table_name="game_faqs")
    op.drop_table("game_faqs")
