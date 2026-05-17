"""Shared test fixtures.

Test DB strategy: honour `DATABASE_URL` if it's set (CI points it at the
postgres:16 service for production parity), otherwise default to a
function-scoped SQLite file so local runs need no infra. Postgres-only
behaviour is gated behind the `integration` marker declared in
pyproject.toml.

Env vars are set BEFORE any `app.*` import so settings + the
module-level SQLAlchemy engine are built from the test config.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# --- Test environment -------------------------------------------------------
# All env wiring happens before any app import.

_UPLOADS_TMP = tempfile.mkdtemp(prefix="nb-uploads-")

os.environ.setdefault("UPLOADS_DIR", _UPLOADS_TMP)
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-key-please-only-for-tests-not-prod-32+chars",
)
# The scheduler spins up a background sweep against the DB on lifespan
# startup. Off for tests so we don't race the fixtures or leak jobs
# between runs.
os.environ.setdefault("AUTO_CANCEL_PENDING_ENABLED", "false")

if "DATABASE_URL" not in os.environ:
    _sqlite_path = Path(tempfile.mkdtemp(prefix="nb-test-db-")) / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_sqlite_path}"

# Now safe to import the app.
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import AsyncSessionLocal, engine, get_db  # noqa: E402
from app.features.users.models import User  # noqa: E402
from app.main import app  # noqa: E402
from app.shared import cache as cache_module  # noqa: E402

IS_SQLITE = engine.url.get_backend_name() == "sqlite"


def pytest_collection_modifyitems(config, items):
    """Skip @pytest.mark.integration tests when the backend is SQLite.

    Important: check `iter_markers` not `keywords` — `keywords` also
    matches the test's containing directory name, so `tests/integration/`
    would auto-skip every file under it. We only want explicit markers.
    """
    if not IS_SQLITE:
        return
    skip = pytest.mark.skip(reason="integration test requires real Postgres")
    for item in items:
        if any(m.name == "integration" for m in item.iter_markers()):
            item.add_marker(skip)


# --- DB lifecycle -----------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def _fresh_cache():
    """Tests run cache-free by default. Individual tests opt in with
    `fakeredis_client` below if they need cache behaviour. Reset state
    around every test so module-level `_client` / `_disabled` flags from
    one test don't leak into the next.
    """
    cache_module.set_client_for_testing(None)
    yield
    cache_module.set_client_for_testing(None)


@pytest_asyncio.fixture
async def fakeredis_client():
    """In-process fakeredis (async). Use this fixture when a test needs
    real cache behaviour (HIT/MISS/SCAN) without spinning up a server."""
    from fakeredis.aioredis import FakeRedis

    client = FakeRedis(decode_responses=True)
    cache_module.set_client_for_testing(client)
    yield client
    cache_module.set_client_for_testing(None)
    await client.aclose()


@pytest_asyncio.fixture(autouse=True)
async def _fresh_schema():
    """Create + drop the schema around every test for full isolation.

    `engine.dispose()` is critical on asyncpg/Postgres: pytest-asyncio
    spins up a fresh event loop per test (function-scoped default), but
    the module-level engine caches connections from prior tests' loops.
    Reusing one across loops raises "Task got Future attached to a
    different loop". SQLite happens to tolerate this because aiosqlite
    talks to a worker thread, not the loop directly — which is why this
    only burned in CI. Disposing the pool first forces fresh connections
    bound to the current test's loop.
    """
    await engine.dispose()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session


# --- HTTP client ------------------------------------------------------------


@pytest_asyncio.fixture
async def client():
    """Async test client. Lifespan is not entered — the lifespan starts
    the APScheduler, which we don't want firing under tests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def client_with_db(db_session):
    """Same as `client`, but DB session is overridden so the request and
    the test see the same data without committing twice."""

    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


# --- Users + tokens ---------------------------------------------------------


async def _make_user(
    db,
    *,
    email: str,
    role: str,
    password: str = "TestPass123!",
) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=email.split("@")[0],
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def superadmin_user(db_session):
    return await _make_user(db_session, email="super@test.io", role="superadmin")


@pytest_asyncio.fixture
async def admin_user(db_session):
    return await _make_user(db_session, email="admin@test.io", role="admin")


@pytest_asyncio.fixture
async def manager_user(db_session):
    return await _make_user(db_session, email="manager@test.io", role="manager")


@pytest_asyncio.fixture
async def viewer_user(db_session):
    return await _make_user(db_session, email="viewer@test.io", role="viewer")


def _bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


@pytest.fixture
def auth_headers():
    """Helper: tests call `auth_headers(user)` to get bearer headers."""
    return _bearer


# --- Domain fixtures --------------------------------------------------------


@pytest_asyncio.fixture
async def sample_game(db_session):
    from app.core.constants import GameStatus
    from app.features.games.models import Game

    game = Game(
        slug="gta5",
        name="GTA 5 Online",
        description="GTA Online boosting",
        sort_order=0,
        status=GameStatus.ACTIVE,
    )
    db_session.add(game)
    await db_session.commit()
    await db_session.refresh(game)
    return game


@pytest_asyncio.fixture
async def sample_service(db_session, sample_game):
    from app.core.constants import Platform
    from app.features.services.models import Service

    service = Service(
        game_id=sample_game.id,
        slug="gta-cash-cars-ps",
        title="GTA Cash + Cars (PS)",
        platform=Platform.PS,
        description=["First", "Second"],
        what_you_get=[{"title": "Cash", "lead": "You get", "items": ["a", "b"]}],
        sections=[{"title": "Section", "texts": ["txt"]}],
        is_featured=True,
        sort_order=0,
        is_active=True,
        is_deleted=False,
    )
    db_session.add(service)
    await db_session.commit()
    await db_session.refresh(service)
    return service
