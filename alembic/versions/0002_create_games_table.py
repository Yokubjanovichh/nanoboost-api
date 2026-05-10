"""create games table

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-07 00:01:00

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "games",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
    )

    # Partial unique index on slug — only enforced for non-deleted rows.
    op.create_index(
        "uq_games_slug_active",
        "games",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )

    # Lookup index for sorted active games (used by /public/games and admin list).
    op.create_index(
        "ix_games_active_sort",
        "games",
        ["is_active", "sort_order"],
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index("ix_games_active_sort", table_name="games")
    op.drop_index("uq_games_slug_active", table_name="games")
    op.drop_table("games")
