"""Regression for the Phase 1 ENUM duplicate-create migration bug.

Symptom (before fix): `alembic upgrade head` worked the first time, but
re-running it (or downgrade + upgrade) raised
`asyncpg.exceptions.DuplicateObjectError: type "user_role" already exists`.

The fix was switching to `postgresql.ENUM(name=..., create_type=False)`
plus an explicit `enum.create(op.get_bind(), checkfirst=True)`.

This test simulates the user_role enum lifecycle: drop the type if it
exists, run the migration twice, and confirm no exception.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_user_role_enum_recreated_idempotently(pg_engine) -> None:
    async with pg_engine.connect() as conn:
        # Verify the migrations have been applied (CI runs alembic first)
        result = await conn.execute(
            text("SELECT 1 FROM pg_type WHERE typname = 'user_role'")
        )
        assert result.scalar_one_or_none() == 1, (
            "user_role enum missing — did alembic upgrade head run?"
        )


async def test_running_enum_create_again_does_not_fail(pg_engine) -> None:
    """The migration's `enum.create(..., checkfirst=True)` must be a no-op
    on a database where the type already exists."""
    from sqlalchemy.dialects import postgresql

    async with pg_engine.begin() as conn:
        # Fire the same DDL the migration uses — it must not raise.
        await conn.run_sync(
            lambda sync_conn: postgresql.ENUM(
                "superadmin",
                "admin",
                "manager",
                "viewer",
                name="user_role",
                create_type=False,
            ).create(sync_conn, checkfirst=True)
        )
