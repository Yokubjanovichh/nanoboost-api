"""game_status enum: active / coming_soon / hidden, replaces is_active

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-17 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create the enum type (first appearance — create_type=True is fine
    #    here; the column declaration below uses create_type=False to avoid
    #    the duplicate-create regression we hit in Phase 1).
    game_status = postgresql.ENUM(
        "active",
        "coming_soon",
        "hidden",
        name="game_status",
        create_type=False,
    )
    game_status.create(op.get_bind(), checkfirst=True)

    # 2. Add the column with a server-default so existing rows get 'active'
    #    automatically.
    op.add_column(
        "games",
        sa.Column(
            "status",
            game_status,
            nullable=False,
            server_default="active",
        ),
    )

    # 3. Backfill the only non-default case (previously hidden rows).
    op.execute("UPDATE games SET status = 'hidden' WHERE is_active = false")

    # 4. Drop the legacy boolean — the enum is now the source of truth.
    op.drop_column("games", "is_active")


def downgrade() -> None:
    op.add_column(
        "games",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.execute("UPDATE games SET is_active = false WHERE status = 'hidden'")
    op.drop_column("games", "status")
    # Drop the enum type — only safe because no other table references it.
    op.execute("DROP TYPE IF EXISTS game_status")
