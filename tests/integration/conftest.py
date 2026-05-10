"""Postgres-only integration test fixtures.

Skipped under SQLite by the project-level `pytest_collection_modifyitems`
hook in tests/conftest.py. To run:

    docker compose --profile test up -d postgres-test
    DATABASE_URL=postgresql+asyncpg://nanoboost:nanoboost@localhost:5433/nanoboost_test \
      alembic upgrade head
    DATABASE_URL=postgresql+asyncpg://nanoboost:nanoboost@localhost:5433/nanoboost_test \
      pytest -m integration
"""

from __future__ import annotations

import os

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def pg_engine():
    """Connect to the integration Postgres provided by docker-compose
    (profile=test) or by the GitHub Actions service container."""
    url = os.environ["DATABASE_URL"]
    assert "postgresql" in url, "Integration tests require a Postgres URL"
    engine = create_async_engine(url, future=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_engine) -> AsyncSession:
    factory = async_sessionmaker(
        bind=pg_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
