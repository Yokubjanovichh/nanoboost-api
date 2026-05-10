"""create reviews table

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-08 00:01:00

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("author_name", sa.String(length=100), nullable=False),
        sa.Column(
            "service_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("services.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "is_featured",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="0"
        ),
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
        sa.CheckConstraint(
            "rating >= 1 AND rating <= 5", name="ck_reviews_rating_range"
        ),
    )
    op.create_index(
        "ix_reviews_service_active",
        "reviews",
        ["service_id"],
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_reviews_featured_sort",
        "reviews",
        ["is_featured", "sort_order"],
        postgresql_where=sa.text("is_active = true AND is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index("ix_reviews_featured_sort", table_name="reviews")
    op.drop_index("ix_reviews_service_active", table_name="reviews")
    op.drop_table("reviews")
