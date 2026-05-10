"""create services and service_options tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-07 00:02:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    service_platform = postgresql.ENUM(
        "ps", "xbox", "pc",
        name="service_platform",
        create_type=False,
    )
    service_platform.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "services",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "game_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("games.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(length=150), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("platform", service_platform, nullable=False),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("image_alt", sa.String(length=300), nullable=True),
        sa.Column(
            "description",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "what_you_get",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "sections",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("seo_title", sa.String(length=300), nullable=True),
        sa.Column("seo_description", sa.String(length=500), nullable=True),
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
    )

    # Slug unique only among non-deleted services.
    op.create_index(
        "uq_services_slug_active",
        "services",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )

    # Lookup index for admin filters: by game/platform/active state.
    op.create_index(
        "ix_services_game_platform_active",
        "services",
        ["game_id", "platform", "is_active"],
        postgresql_where=sa.text("is_deleted = false"),
    )

    # Featured listing index for the homepage.
    op.create_index(
        "ix_services_featured_sort",
        "services",
        ["is_featured", "sort_order"],
        postgresql_where=sa.text("is_active = true AND is_deleted = false"),
    )

    # service_options table
    op.create_table(
        "service_options",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "service_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("services.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column(
            "price_usd",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
        ),
        sa.Column(
            "price_eur",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="0"
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
        sa.CheckConstraint("price_usd >= 0", name="ck_service_options_price_usd_nonneg"),
        sa.CheckConstraint("price_eur >= 0", name="ck_service_options_price_eur_nonneg"),
    )

    op.create_index(
        "ix_service_options_service_sort",
        "service_options",
        ["service_id", "sort_order"],
    )

    # Only one option per service can be default.
    op.create_index(
        "uq_service_options_default_per_service",
        "service_options",
        ["service_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_service_options_default_per_service", table_name="service_options"
    )
    op.drop_index("ix_service_options_service_sort", table_name="service_options")
    op.drop_table("service_options")

    op.drop_index("ix_services_featured_sort", table_name="services")
    op.drop_index("ix_services_game_platform_active", table_name="services")
    op.drop_index("uq_services_slug_active", table_name="services")
    op.drop_table("services")

    sa.Enum(name="service_platform").drop(op.get_bind(), checkfirst=True)
