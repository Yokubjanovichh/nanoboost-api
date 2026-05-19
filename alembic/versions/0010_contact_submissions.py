"""contact_submissions: public contact-form storage

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-18 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # preferred_contact uses a plain VARCHAR — the value set is small and
    # likely to grow (signal, sms, …); the cost of an ALTER TYPE on a
    # public-write table outweighs the strict-typing payoff at this stage.
    op.create_table(
        "contact_submissions",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("preferred_contact", sa.String(20), nullable=False),
        sa.Column("handle", sa.String(200), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "client_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # INET on Postgres for cheap subnet queries; cross-dialect to
        # String elsewhere so SQLite tests stay green.
        sa.Column(
            "ip_address",
            sa.String(45).with_variant(postgresql.INET(), "postgresql"),
            nullable=True,
        ),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "idx_contact_submissions_created_at",
        "contact_submissions",
        [sa.text("created_at DESC")],
    )
    # Partial index — admin lookups by client are sparse, so the index
    # only carries the linked rows.
    op.create_index(
        "idx_contact_submissions_client",
        "contact_submissions",
        ["client_id"],
        postgresql_where=sa.text("client_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_contact_submissions_client", table_name="contact_submissions")
    op.drop_index("idx_contact_submissions_created_at", table_name="contact_submissions")
    op.drop_table("contact_submissions")
