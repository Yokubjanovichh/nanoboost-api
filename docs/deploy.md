# Production Deployment

Target stack (V1):

```
Internet → Cloudflare (DNS + SSL + DDoS) → Railway (Docker) → Postgres (Railway managed)
```

V2 migration path: Neon (Postgres) + Render/Fly.io (API) — same image,
just point `DATABASE_URL` elsewhere.

---

## 1. Prerequisites

- Railway account: https://railway.app
- GitHub repository connected to Railway
- Domain control: `api.nanoboost.io` DNS record
- Cloudflare account (recommended)
- @BotFather Telegram bot token + admin chat id
- SMTP credentials (Gmail App Password works for V1)

---

## 2. Railway Setup

1. **New Project → Deploy from GitHub repo** → select `nanoboost-api`.
2. **Add Postgres plugin** (Database → New → PostgreSQL).
3. Railway injects `DATABASE_URL` automatically into the API service.
4. **Settings → Service → Source** → confirm Dockerfile is detected.

Build runs the existing Dockerfile. The container start command in
`docker-compose.yml` (`alembic upgrade head && create_superuser && uvicorn`)
also applies on Railway — copy it into the **Custom Start Command** field if
Railway doesn't pick up the compose CMD.

---

## 3. Environment Variables (Railway dashboard)

Mark all secret values as Railway "Secret" (encrypted at rest).

```
ENVIRONMENT=prod

# JWT (generate: python -c "import secrets; print(secrets.token_urlsafe(64))")
JWT_SECRET_KEY=<64-char random>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

# DATABASE_URL — provided by Railway Postgres plugin

# CORS
CORS_ORIGINS=["https://admin.nanoboost.io","https://nanoboost.io"]

# Storage
STORAGE_BACKEND=local
UPLOADS_DIR=/app/uploads
UPLOADS_URL_PREFIX=/uploads
MAX_UPLOAD_SIZE_BYTES=5242880

# Notifications
NOTIFICATIONS_ENABLED=true

TG_ENABLED=true
TG_BOT_TOKEN=<from @BotFather>
TG_CHAT_ID=<admin chat>

SMTP_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=<email>
SMTP_PASSWORD=<gmail app password>
SMTP_FROM=orders@nanoboost.io
NOTIFY_EMAIL=admin@nanoboost.io

# Initial superuser — change immediately after first login
SEED_SUPERUSER_EMAIL=admin@nanoboost.io
SEED_SUPERUSER_PASSWORD=<strong-pre-share-once>
SEED_SUPERUSER_NAME=Root Admin
```

> **Critical:** `JWT_SECRET_KEY` rotation requires re-issuing every active
> token (logs everyone out). Set it once at deploy time and never reuse the
> dev value.

---

## 4. First Deploy

```bash
git push origin main           # GitHub Actions runs CI → builds image → triggers Railway
```

CI pipeline (`.github/workflows/ci.yml`):

1. `lint` (ruff)
2. `test-unit` (SQLite, ~30s)
3. `test-integration` (Postgres 16 service container, integration markers)
4. `build` — push image to GHCR with git SHA tag
5. `deploy` — POST to Railway deploy hook

On Railway:
- Pulls the new image
- Runs `alembic upgrade head` at container start
- Runs `python -m app.scripts.create_superuser` (idempotent)
- Starts Uvicorn

Watch logs in Railway dashboard. First-deploy expectations:

```
INFO  alembic.runtime.migration: Will assume non-transactional DDL.
INFO  alembic.runtime.migration: Running upgrade  -> 0001, create users table
...
INFO  alembic.runtime.migration: Running upgrade 0005 -> 0006, create reviews
INFO  nanoboost.seed: Superuser created: admin@nanoboost.io
INFO  uvicorn: Application startup complete.
```

---

## 5. Domain Setup

### Railway side
**Settings → Networking → Custom Domain** → add `api.nanoboost.io`.
Railway returns a CNAME target like `*.up.railway.app`.

### Cloudflare side
DNS record:
```
Type    Name    Content                          Proxy
CNAME   api     <railway-cname>.up.railway.app   ✅ Proxied (orange)
```

SSL/TLS mode: **Full (strict)**. Cloudflare's edge cert + Railway's
backend cert form a complete chain.

---

## 6. Verification

```bash
curl https://api.nanoboost.io/health
# {"status":"ok"}

curl https://api.nanoboost.io/docs
# Swagger UI

curl -X POST https://api.nanoboost.io/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@nanoboost.io","password":"<seeded>"}'
# Returns access_token + refresh_token
```

If `/docs` returns 404: confirm `ENVIRONMENT=prod` does not disable docs
in your config (current code keeps them enabled — change later if you
want auth-gated docs).

---

## 7. Initial Data Import (legacy services-data.js)

One-off, after the first deploy.

### Step 7.1 — Frontend export
Frontend developer runs in the public-site repo:

```bash
node -e "global.window={};require('./scripts/services-data.js');\
console.log(JSON.stringify(window.NB_SERVICE_CONFIG, null, 2))" \
  > services-data.json
```

### Step 7.2 — Hand off to Backend
```bash
# From a machine with Railway CLI access:
railway shell
# inside the container:
cat > /tmp/services-data.json <<'EOF'
<paste JSON>
EOF
```

(or use `railway run` to copy a local file via env var, or scp via the
Railway shell.)

### Step 7.3 — Dry-run
```bash
python -m scripts.import_legacy_services \
  --input /tmp/services-data.json \
  --default-game-slug gta5 \
  --create-game-if-missing \
  --game-name "GTA 5 Online" \
  --dry-run
```

Expected: `would-create: 17, skipped: 0`.

### Step 7.4 — Real run
Re-run without `--dry-run`. Verify:

```bash
curl https://api.nanoboost.io/api/v1/public/services?game=gta5 | jq '. | length'
# 17 (or whatever the export count was)
```

---

## 8. Post-Deploy Checklist

- [ ] `/health` returns 200
- [ ] `/docs` Swagger loads
- [ ] Login works with seeded credentials
- [ ] **Change superadmin password** via `PATCH /api/v1/users/{id}` with
      `{"password": "<new-strong-password>"}`
- [ ] Public order endpoint smoke-tested (`POST /api/v1/public/orders`)
- [ ] Telegram notification arrives in admin chat (test with a fake order)
- [ ] Email notification arrives at `NOTIFY_EMAIL`
- [ ] Cloudflare proxy active (orange cloud ON)
- [ ] UptimeRobot monitor pointing at `/health` (5-min interval, free)

---

## 9. Backup & Recovery

### Backup (V1)
Railway managed Postgres takes daily snapshots automatically. Free tier
keeps 7 days; paid tiers keep 30+. No additional script required.

### Recovery
Railway dashboard → Postgres service → **Backups** → restore by date.
This creates a new Postgres instance — repoint `DATABASE_URL` and
redeploy.

### V2 hardening
- Migrate to Neon Postgres (better tier free, branching, PITR).
- Add `pg_dump` cron in CI:
  ```yaml
  schedule:
    - cron: "0 3 * * *"   # daily 03:00 UTC
  ```
  + S3 archival for off-site copies.

---

## 10. Rollback

### Application code
Railway dashboard → **Deployments** → previous successful deploy →
**Redeploy**. The image is already in GHCR, this is a metadata-only flip.

### Database schema
Avoid downgrading migrations in production except for emergencies — they
are tested but data backfills are one-way.

If you must:
```bash
railway run alembic downgrade -1
```

Better: forward-fix with a new migration that reverses the offending
change.

---

## 11. Monitoring

| What | Where |
|------|-------|
| Logs | Railway dashboard → service → Logs (live tail) |
| Metrics (CPU, RAM, requests) | Railway dashboard → Metrics |
| Uptime | UptimeRobot — `/health` endpoint, 5-min check |
| Errors | Application logs. V2: add Sentry (`sentry-sdk[fastapi]`) |
| Database | Railway Postgres metrics (connections, query latency) |

---

## 12. Secret Rotation

| Secret | Rotation cadence | Effect |
|--------|------------------|--------|
| `JWT_SECRET_KEY` | Every 6 months OR on suspected compromise | Logs everyone out |
| `TG_BOT_TOKEN` | Only if leaked | New token from @BotFather |
| `SMTP_PASSWORD` | Yearly | Generate new Gmail app password |
| `SEED_SUPERUSER_PASSWORD` | After first login (one-time) | Use API PATCH |

To rotate: update Railway env var → service redeploys automatically.

---

## 13. Known Limits (V1)

- **Single Railway region** (no multi-region failover until V2)
- **No Redis/cache** (dashboard endpoints recomputed on every request —
  fine for current order volume; revisit if dashboards lag)
- **Notifications best-effort** — no retry queue, fail logs only
- **Local file uploads** — image migration to S3/Cloudinary deferred to
  V2 (Strategy pattern is in place: `app/shared/storage/`)

---

## Quick reference

```bash
# Health
curl https://api.nanoboost.io/health

# Trigger redeploy (Railway CLI)
railway up

# Tail logs
railway logs

# Run a one-off migration / script
railway run alembic upgrade head
railway run python -m app.scripts.create_superuser
railway run python -m scripts.import_legacy_services --input ... --dry-run
```
