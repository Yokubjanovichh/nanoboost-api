"""dual image fields — split image_url into desktop + mobile (games, services)

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-09 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- games ---
    op.alter_column("games", "image_url", new_column_name="image_desktop_url")
    op.add_column(
        "games",
        sa.Column("image_mobile_url", sa.String(length=500), nullable=True),
    )

    # --- services ---
    op.alter_column("services", "image_url", new_column_name="image_desktop_url")
    op.add_column(
        "services",
        sa.Column("image_mobile_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("services", "image_mobile_url")
    op.alter_column("services", "image_desktop_url", new_column_name="image_url")
    op.drop_column("games", "image_mobile_url")
    op.alter_column("games", "image_desktop_url", new_column_name="image_url")
