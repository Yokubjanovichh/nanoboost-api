import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-must-be-at-least-32-chars-long")
os.environ.setdefault("CORS_ORIGINS", '["http://localhost:3000"]')


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    """Skip @pytest.mark.integration tests when not running on Postgres."""
    if "postgresql" in os.environ["DATABASE_URL"]:
        return
    skip_marker = pytest.mark.skip(reason="integration tests require Postgres")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)

from app.core.config import settings  # noqa: E402
from app.core.constants import UserRole  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.features.users.models import User  # noqa: E402
from app.main import app  # noqa: E402

# SQLite needs Enum stored as string; native_enum=False handled by SAEnum default.
# UUID needs custom handling — but SQLAlchemy 2 handles uuid for sqlite via str.
# We patch the engine to use sqlite for tests.

@pytest_asyncio.fixture(scope="function")
async def db_engine():
    engine = create_async_engine(
        settings.DATABASE_URL,
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def superadmin_user(db_session: AsyncSession) -> User:
    user = User(
        email="root@nanoboost.io",
        password_hash=hash_password("RootPass123!"),
        full_name="Root Admin",
        role=UserRole.SUPERADMIN,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def viewer_user(db_session: AsyncSession) -> User:
    user = User(
        email="viewer@nanoboost.io",
        password_hash=hash_password("ViewerPass123!"),
        full_name="Viewer",
        role=UserRole.VIEWER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def superadmin_token(superadmin_user: User) -> str:
    return create_access_token(superadmin_user.id, superadmin_user.role)


@pytest.fixture
def viewer_token(viewer_user: User) -> str:
    return create_access_token(viewer_user.id, viewer_user.role)


@pytest.fixture
def auth_header():
    def _make(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    return _make
