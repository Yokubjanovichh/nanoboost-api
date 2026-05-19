# Nanoboost Admin API

REST API for the Nanoboost public site (orders) and internal admin panel
(games, services, orders, clients, reviews).

Stack: **FastAPI + SQLAlchemy 2 (async) + PostgreSQL 16 + Alembic + Pydantic v2 + JWT**.

---

## API Contract

Single source of truth for routes, response shapes, error formats,
and the breaking-change protocol:
[`docs/api-contract.md`](docs/api-contract.md).

Live machine-readable schema: [`docs/openapi-snapshot.json`](docs/openapi-snapshot.json)
(regenerate after route changes: `python -m scripts.dump_openapi_snapshot`).

CI fails any PR that changes the schema without refreshing the
snapshot — contract drift surfaces in review, not in production.

---

## Requirements

- Docker & Docker Compose
- (optional, for local non-docker dev) Python 3.12+

## Quickstart (Docker)

```bash
cp .env.example .env
docker compose up --build
```

The `api` container automatically runs:

1. `alembic upgrade head` (creates `users` table + `user_role` enum)
2. `python -m app.scripts.create_superuser` (idempotent — only creates if missing)
3. `uvicorn app.main:app --reload`

After startup:

| URL                                | What                          |
| ---------------------------------- | ----------------------------- |
| `http://localhost:8000/health`     | `{"status": "ok"}`            |
| `http://localhost:8000/docs`       | Swagger UI                    |
| `http://localhost:8000/redoc`      | ReDoc                         |
| `http://localhost:8000/openapi.json` | OpenAPI schema              |

### Default seeded credentials (dev only — change in production)

```
email:    admin@nanoboost.io
password: ChangeMeImmediately123!
```

---

## Local development (without Docker)

```bash
python -m venv .venv
.venv\Scripts\activate         # Windows
# source .venv/bin/activate    # Linux/Mac

pip install -e ".[dev]"

# Postgres must be running locally on port 5432 (or update DATABASE_URL)
alembic upgrade head
python -m app.scripts.create_superuser
uvicorn app.main:app --reload
```

---

## Testing

Suite layout:

```
tests/
├── conftest.py            Shared fixtures (DB session, test client, users, sample data)
├── unit/                  Pure-function tests (security, payment strategy, transitions)
├── integration/           HTTP → middleware → router → DB endpoint tests
├── contracts/             Runtime response-shape snapshots (see "Contract testing" below)
└── e2e/                   Startup + smoke (incident-coverage tests live here)
```

### Contract testing

`tests/contracts/` snapshots the **runtime shape** of every public
endpoint. The OpenAPI snapshot (`docs/openapi-snapshot.json`) catches
static-schema drift; contract tests catch what the schema can't see —
`response_model_exclude`, computed fields, JSON-serialisation quirks.

Adding/removing/retyping a Pydantic field fails the matching test
with a one-line diff:

```
E   AssertionError: assert [+ received] == [- snapshot]
E       ...
E   -     'service_count': 'int',
E       ...
```

When the change is **intentional**, regenerate and commit — the diff
becomes part of the PR for Manager + clients to review:

```bash
uv run pytest tests/contracts/ --snapshot-update
git add tests/contracts/__snapshots__/
```

Snapshots live in `tests/contracts/__snapshots__/*.ambr` — plain text
[syrupy](https://github.com/syrupy-project/syrupy) format that reads
cleanly in PR diffs.

### Run locally (fast — SQLite default)

```bash
pytest                          # full suite on file-backed SQLite, ~25s
pytest tests/unit/              # pure-function tests, no DB, <1s
pytest tests/e2e/test_startup.py -v   # the incident-coverage test (see note below)
pytest --cov=app --cov-report=term    # with coverage
```

Local default: a temp SQLite file per run, no Docker needed. Tests
marked `@pytest.mark.integration` (Postgres-specific behaviour: ENUM
duplicate-create, JSONB, `pg_advisory_xact_lock`) auto-skip under
SQLite — the conftest checks the actual marker, not the directory name.

### Run with real Postgres (production parity)

```bash
docker compose --profile test up -d postgres-test
DATABASE_URL=postgresql+asyncpg://nanoboost:nanoboost@localhost:5433/nanoboost_test \
  alembic upgrade head
DATABASE_URL=postgresql+asyncpg://nanoboost:nanoboost@localhost:5433/nanoboost_test \
  pytest
```

### CI

Every push and PR runs `pytest tests/ --cov=app --cov-fail-under=60`
against a real `postgres:16` service. The job is named `test` and is
required by branch protection on `main` — a red test blocks merge.

The single test that would have caught the apscheduler P0
(`tests/e2e/test_startup.py::test_app_imports_without_error`) lives at
the top of the e2e suite; it imports `app.main` and would have failed
CI before PR #15 could merge if it had been in place.

### Lint + format

```bash
ruff check .
ruff format --check .
```

---

## Caching

`/public/*` reads are Redis-cached with smart invalidation. The cache
is **optional** — empty `REDIS_URL` (or an unreachable broker) makes
every request hit the DB directly and respond with `X-Cache: BYPASS`.
The API stays up if Redis goes down.

### Keys + TTLs

| Endpoint | Key shape | TTL |
|---|---|---|
| `GET /public/games` | `public:games:v1` | 300s |
| `GET /public/services` | `public:services:v1:game=<g>:platform=<p>:featured=<f>:page=<n>:size=<n>` | 180s |
| `GET /public/services/{slug}` | `public:services:v1:slug=<slug>` | 180s |
| `GET /public/reviews` | `public:reviews:v1:service_id=<id>:featured=<f>` | 600s |

The `v1` segment is a schema version — bump it on any response-shape
change to invalidate the entire layer atomically.

### Invalidation map (admin writes)

| Admin write | Patterns cleared |
|---|---|
| Game CRUD | `public:games:*` |
| Service CRUD (incl. options) | `public:services:*` **and** `public:games:*` (service_count lives on the games payload) |
| Review CRUD | `public:reviews:*` |

Deletion uses `SCAN` + `DEL`, never `KEYS *` (which blocks Redis on
large keyspaces).

### X-Cache header

Every cached endpoint returns one of:

- `HIT` — served from Redis
- `MISS` — computed and stored
- `BYPASS` — cache unavailable, served from DB (no store)

### Stampede protection

When a cached entry expires, concurrent requests don't all stampede
the DB. The cache layer takes a Redis lock around the recompute:

- First request wins the lock, runs the query, fills the cache.
- Other concurrent requests briefly poll the cache (up to ~500ms);
  when the value lands, they return `X-Cache: HIT`.
- If the lock holder takes too long or crashes, waiters fall back to
  computing themselves so nothing deadlocks.

The lock release is ownership-checked (Lua `compare-and-delete`) so
a TTL-expired lock can't be deleted by its previous owner. Redis-down
short-circuits to a direct compute — losing stampede protection is
preferable to refusing traffic.

`cache_get_or_compute(...)` exposes the same pattern for any future
code path that wants Python-level cache-aside semantics.

### Health

`GET /health` returns `{"status": "ok", "redis": "ok|down|disabled"}`.
`disabled` means no `REDIS_URL` is configured. `down` means the URL is
set but the broker isn't responding — endpoints stay up via BYPASS.

### Local dev

```bash
docker compose up redis -d   # or `docker run --rm -p 6379:6379 redis:7-alpine`
export REDIS_URL=redis://localhost:6379/0
uvicorn app.main:app --reload
```

Tests don't need a real Redis — `tests/conftest.py` exposes a
`fakeredis_client` fixture that swaps an in-process fake in for the
duration of a test. CI also runs `redis:7-alpine` as a service for
end-to-end coverage.

---

## Observability

Every request produces structured logs with a correlation `request_id`,
the resolved `user_id` (or `null` for anonymous traffic), HTTP method,
path, status, and duration. Production emits one JSON line per record
(Railway / Datadog / Loki ingest these directly); local dev defaults
to a colored console renderer for readability.

### Settings

| Env | Default | Meaning |
|---|---|---|
| `LOG_FORMAT` | `auto` | `json`, `pretty`, or `auto` (json in prod, pretty otherwise) |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |

### Request lifecycle events

Every HTTP request produces two records — one at receipt, one at
completion — with the same `request_id`:

```json
{"event":"request_started","request_id":"7c9f...","method":"GET","path":"/api/v1/public/services","client_ip":"1.2.3.4","user_id":null,"level":"info","timestamp":"2026-05-18T...Z"}
{"event":"request_completed","request_id":"7c9f...","method":"GET","path":"/api/v1/public/services","status":200,"duration_ms":12,"client_ip":"1.2.3.4","user_id":null,"level":"info","timestamp":"2026-05-18T...Z"}
```

5xx responses log at `error` level so Railway alert rules can pin on
`level:error` without false positives from 4xx.

### X-Request-ID

Responses carry an `X-Request-ID` header (the same value as the log
record's `request_id`). Clients can pass one in to thread a trace —
the middleware preserves a caller-supplied value rather than minting
a new one.

### Sensitive data

The middleware never logs request bodies. Sensitive request headers
(`Authorization`, `Cookie`, `X-Webhook-Signature`,
`X-EcomTrade24-Signature`, `X-Api-Key`) are redacted via
`app.shared.middleware.request_logging.redact_headers` for any
code path that does want to log headers.

Auth events emit the email (for failed-login alerting) and `user_id`,
never passwords or hashes.

### Domain events worth grepping

| Event | Where | When |
|---|---|---|
| `auth_login_success` / `auth_login_failed` | `app.features.auth.service` | every login attempt |
| `request_started` / `request_completed` | middleware | every HTTP request |
| `request_failed` | middleware | unhandled exception in the stack |
| `scheduler_started` / `scheduler_job_completed` | scheduler | startup + each sweep |
| `cache_unavailable` / `cache_*_failed` | cache module | broker degradation |

### Local example

```bash
LOG_FORMAT=json LOG_LEVEL=INFO uvicorn app.main:app
# or for dev:
LOG_FORMAT=pretty uvicorn app.main:app --reload
```

---

## Project structure

```
nanoboost-api/
├── alembic/                  Migrations
├── app/
│   ├── api/v1/               API version aggregator
│   ├── core/                 Settings, security, deps, exceptions
│   ├── db/                   Engine, session, base, mixins
│   ├── features/
│   │   ├── auth/             Login / refresh / me
│   │   └── users/            CRUD users
│   ├── shared/               Pagination utilities
│   ├── scripts/              CLI scripts (create_superuser)
│   └── main.py               FastAPI app
├── tests/
│   ├── conftest.py
│   └── features/
└── docker-compose.yml
```

### Architecture rule

`router → service → repository`. Routers never query the DB directly;
services never touch HTTP types.

---

## Production deployment

See [`docs/deploy.md`](docs/deploy.md) for the full Railway + Cloudflare
playbook. Production env template lives in
[`.env.production.example`](.env.production.example).

## CI/CD

`.github/workflows/ci.yml` runs five jobs on every push to `main`:

1. **lint** — ruff check + format
2. **test-unit** — pytest against SQLite (~30s)
3. **test-integration** — pytest `-m integration` against Postgres 16
4. **build** — Docker image, pushed to GHCR (`sha-...` + `latest`)
5. **deploy** — POST to Railway deploy hook (skipped if secret unset)

Required GitHub Secrets:
- `RAILWAY_DEPLOY_HOOK` — deploy hook URL from Railway service settings.

GHCR auth uses the default `GITHUB_TOKEN`; no extra secret required.

## Legacy data import

One-off migration from the public site's `services-data.js`:

```bash
# 1. Frontend: dump JS object as JSON
node -e "global.window={};require('./scripts/services-data.js'); \
  console.log(JSON.stringify(window.NB_SERVICE_CONFIG, null, 2))" \
  > services-data.json

# 2. Backend: import (dry-run first)
docker compose run --rm api \
  python -m scripts.import_legacy_services \
    --input /app/services-data.json \
    --default-game-slug gta5 \
    --create-game-if-missing \
    --game-name "GTA 5 Online" \
    --dry-run

# 3. Real run (drop --dry-run)
```

Idempotent: re-runs `skipped` instead of duplicating.

## API contract (Phase 1 — 6)

### Auth

```
POST /api/v1/auth/login      { email, password }     → TokenResponse
POST /api/v1/auth/refresh    { refresh_token }       → TokenResponse
GET  /api/v1/auth/me         (Bearer token)          → UserRead
```

`TokenResponse`:

```json
{
  "access_token": "eyJhbG...",
  "refresh_token": "eyJhbG...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": { "id": "...", "email": "...", "full_name": "...", "role": "admin" }
}
```

### Users (superadmin only)

```
GET    /api/v1/users?page=1&page_size=20    Paginated<UserRead>
POST   /api/v1/users                         UserCreate → UserRead (201)
GET    /api/v1/users/{id}                    UserRead
PATCH  /api/v1/users/{id}                    UserUpdate → UserRead
DELETE /api/v1/users/{id}                    204 (soft delete: is_active=false)
```

### Games (Phase 2)

```
GET    /api/v1/games                      list (filters: is_active, search, sort)  any role
POST   /api/v1/games                      create                                  manager+
GET    /api/v1/games/{id}                 detail                                  any role
PATCH  /api/v1/games/{id}                 partial update                          manager+
PATCH  /api/v1/games/{id}/toggle          flip is_active                          manager+
DELETE /api/v1/games/{id}                 soft delete                             admin+
POST   /api/v1/games/reorder              bulk sort_order update                  manager+

GET    /api/v1/public/games               public list (active only, no auth)
```

### Services (Phase 3)

```
GET    /api/v1/services                        list (paginated)              any role
POST   /api/v1/services                        create + nested options       manager+
GET    /api/v1/services/{id}                   detail with options + game    any role
PATCH  /api/v1/services/{id}                   partial update                manager+
PATCH  /api/v1/services/{id}/toggle            flip is_active                manager+
PATCH  /api/v1/services/{id}/featured          flip is_featured              manager+
DELETE /api/v1/services/{id}                   soft delete                   admin+
POST   /api/v1/services/reorder                bulk sort_order update        manager+

GET    /api/v1/services/{id}/options                          list options       any role
POST   /api/v1/services/{id}/options                          create option      manager+
PATCH  /api/v1/services/{id}/options/{oid}                    update option      manager+
DELETE /api/v1/services/{id}/options/{oid}                    hard delete        manager+
POST   /api/v1/services/{id}/options/reorder                  reorder options    manager+

GET    /api/v1/public/services?game=&platform=&featured=      public list (no auth)
GET    /api/v1/public/services/{slug}                          public detail
```

List filters: `game_id`, `platform` (`ps|xbox|pc`), `is_active`, `is_featured`,
`search`, `sort` (`sort_order|title|created_at`, prefix `-` for desc).

Setting an option's `is_default=true` automatically clears the previous
default for the same service (atomic, single transaction).

### Schema alignment (migration 0005)

Phase 4 column names were brought in line with the canonical TZ shape:

| Old                          | New                          |
| ---------------------------- | ---------------------------- |
| `orders.discount_usd`        | `orders.discount_amount_usd` |
| `order_items.qty`            | `order_items.quantity`       |
| `order_items.price_usd_at_order` | `order_items.unit_price_usd` |
| `order_items.price_eur_at_order` | `order_items.unit_price_eur` |
| `order_items.line_total_usd` | `order_items.total_price_usd` |
| —                            | `order_items.total_price_eur` (new) |
| —                            | `order_items.option_id` (FK SET NULL) |
| —                            | `order_items.service_snapshot` (JSONB) |
| —                            | `clients.whatsapp` (new) |

`service_snapshot` is frozen at order time. Edits to the source service
no longer mutate the order's snapshot — required for audit/reporting.

Legacy `service_slug` and `service_title` columns are kept for V1
backwards-compatibility and will be dropped in V2.

### Clients (Phase 4)

```
GET    /api/v1/clients                         list (search by email/discord/telegram)  any role
GET    /api/v1/clients/{id}                    detail with stats (orders + spend)        any role
GET    /api/v1/clients/{id}/orders             paginated order history                   any role
PATCH  /api/v1/clients/{id}                    update notes/discord/telegram             manager+
```

### Orders (Phase 4)

```
GET    /api/v1/orders                          list (filters: status, client_id,         any role
                                                       payment_method, date_from/to,
                                                       search by order_number/email,
                                                       sort)
GET    /api/v1/orders/stats                    dashboard counters & breakdown            any role
GET    /api/v1/orders/{id}                     detail with items + client                any role
PATCH  /api/v1/orders/{id}                     update comment + admin_notes              manager+
PATCH  /api/v1/orders/{id}/status              state-machine validated transition        manager+
```

**Order status state machine:**

```
pending  → paid | cancelled
paid     → in_progress | cancelled | refunded
in_progress → completed | cancelled | refunded
completed → refunded
cancelled, refunded → (terminal)
```

Invalid transitions return 409. Same-state transitions return 422.
Status timestamps (`paid_at`, `completed_at`, `cancelled_at`, `refunded_at`)
are set automatically when the corresponding state is reached.

**Order numbers:** `NB-YYYYMMDD-NNNN` (4-digit sequence per day, starts at 1001).
Generation uses `pg_advisory_xact_lock(...)` on Postgres to be safe under
concurrent inserts. Sequence does not roll over across days.

### Dashboard (Phase 6)

```
GET /api/v1/dashboard/overview?period=today|week|month|year      any role
GET /api/v1/dashboard/revenue-chart?period=...                   any role
GET /api/v1/dashboard/top-services?period=...&limit=5            any role
GET /api/v1/dashboard/recent-orders?limit=10                     any role
```

### Notifications (Phase 6)

Strategy pattern in `app/shared/notifications/`:
- `TelegramBackend` (httpx, Markdown, parse_mode)
- `SmtpEmailBackend` (aiosmtplib, plain text)
- `NoOpBackend` when disabled

Triggered (best-effort, via FastAPI `BackgroundTasks`):
- `POST /api/v1/public/orders` → `notify_new_order(order)`
- `PATCH /api/v1/orders/{id}/status` → `notify_status_change(order, old, new)`

Failure of either channel is logged and does **not** affect the HTTP
response or the saved order.

### Reviews (Phase 5)

```
GET    /api/v1/reviews                       list (filters: service_id, is_active,    any role
                                                     is_featured, search, sort)
GET    /api/v1/reviews/{id}                  detail                                   any role
POST   /api/v1/reviews                       create (service_id optional)             manager+
PATCH  /api/v1/reviews/{id}                  partial update                           manager+
PATCH  /api/v1/reviews/{id}/toggle           flip is_active                           manager+
PATCH  /api/v1/reviews/{id}/featured         flip is_featured                         manager+
DELETE /api/v1/reviews/{id}                  soft delete                              admin+
POST   /api/v1/reviews/reorder               bulk sort_order update                   manager+

GET    /api/v1/public/reviews?service_id=&featured=    public list (no auth)
```

Rating must be between 1 and 5 (CHECK constraint). When the linked service
is hard-deleted, `service_id` becomes NULL (FK SET NULL).

### Public Orders (Phase 5)

```
POST /api/v1/public/orders     auth-less, called by the public website checkout
```

Request body trusts only IDs and quantities. Prices, snapshots, totals
and discount percentage are computed server-side from the live
`services` / `service_options` tables. USDT (TRC20) payment automatically
applies a 5% discount.

```json
POST /api/v1/public/orders
{
  "email": "buyer@example.com",
  "discord": "buyer#1234",
  "telegram": "@buyer",
  "whatsapp": "+380501234567",
  "payment_method": "paypal" | "usdt_trc20",
  "display_currency": "USD" | "EUR",
  "comment": "...",
  "items": [
    { "service_id": "<uuid>", "option_id": "<uuid>", "quantity": 1 }
  ]
}

→ 201 Created
{
  "order_number": "NB-20260508-1001",
  "status": "pending",
  "final_total_usd": 19.99,
  "display_currency": "USD",
  "created_at": "2026-05-08T12:34:56Z"
}
```

Errors:
- `422` — invalid email, missing items, service inactive/missing,
  option doesn't belong to the supplied service.
- `500` — order_number generation race exhausted (advisory lock failure).

### Uploads (Phase 2)

```
POST /api/v1/uploads     multipart/form-data: file + folder      manager+
                          → { url, filename, folder, size_bytes, content_type }
GET  /uploads/<f>/<n>    static file (no auth)
```

Validation: `image/webp|jpeg|png`, max 5MB, magic-byte check via PIL,
folder ∈ {games, services, reviews, misc}.

### Curl examples

```bash
# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@nanoboost.io","password":"ChangeMeImmediately123!"}'

# Me
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN"

# Create game
curl -X POST http://localhost:8000/api/v1/games \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"slug":"gta5","name":"GTA 5 Online","sort_order":1}'

# List games (paginated, search)
curl "http://localhost:8000/api/v1/games?page=1&page_size=20&search=gta" \
  -H "Authorization: Bearer $TOKEN"

# Toggle active
curl -X PATCH http://localhost:8000/api/v1/games/<UUID>/toggle \
  -H "Authorization: Bearer $TOKEN"

# Reorder
curl -X POST http://localhost:8000/api/v1/games/reorder \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"items":[{"id":"<uuid1>","sort_order":0},{"id":"<uuid2>","sort_order":1}]}'

# Public games (no auth)
curl http://localhost:8000/api/v1/public/games

# Upload image
curl -X POST http://localhost:8000/api/v1/uploads \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@logo.webp;type=image/webp" \
  -F "folder=games"
```

---

## Adding a new role (future)

The `user_role` Postgres native ENUM requires an explicit migration:

```python
op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'editor'")
```

Place this inside an Alembic `op.execute(...)` migration. Postgres ENUM
ADD VALUE cannot run inside a transaction in older versions — use
`with op.get_context().autocommit_block():` if needed.

---

## Roles

| Role         | Powers (Phase 1)                            |
| ------------ | ------------------------------------------- |
| `superadmin` | Full access. Only role that manages users.  |
| `admin`      | (Reserved for Phase 2+ — games/services)    |
| `manager`    | (Reserved for Phase 2+ — orders/clients)    |
| `viewer`     | (Reserved for Phase 2+ — read-only access)  |

---

## Conventions

- All endpoints under `/api/v1/`.
- All DB access async (`AsyncSession`).
- Errors return `{ "detail": "..." }` with appropriate HTTP status.
- Passwords: bcrypt, work factor 12.
- JWT claims: `sub` (user_id), `role`, `type` (access/refresh), `iat`, `exp`.
- Access token TTL: 60 minutes. Refresh token TTL: 7 days.
