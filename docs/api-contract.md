# Nanoboost API Contract

**Single source of truth** for what the Nanoboost backend exposes,
how clients talk to it, and how breaking changes are coordinated.

If you're investigating a 4xx, a missing field, or a "regression",
**start here first** — most of the time the answer is in this file
or in [`openapi-snapshot.json`](openapi-snapshot.json) alongside it.

---

## 1. Base URL + versioning

| Environment | Base URL |
|---|---|
| Production | `https://nanoboost-api-production.up.railway.app/api/v1` |
| Local dev | `http://localhost:8000/api/v1` |

Every route lives under `/api/v1/`. There is no `/public/...` route
without the prefix — a 404 on a prefix-less URL is the URL, not a
regression.

### Versioning policy

- **URL-based**: `/api/v1`, `/api/v2`, …
- Breaking changes ship as a **new major version**, served alongside
  the old one. The previous version stays live for **3 months**.
- See [Breaking change protocol](#breaking-change-protocol) below.

### Auto-generated artifacts

| URL | Purpose |
|---|---|
| `/openapi.json` | live OpenAPI 3.1 schema |
| `/docs` | Swagger UI |
| `/redoc` | ReDoc |

The committed [`openapi-snapshot.json`](openapi-snapshot.json) is the
last-known-good snapshot — CI fails if a PR changes a route without
regenerating it.

---

## 2. Public endpoints

These endpoints power the storefront and webhook integrations. No
auth on the read paths; the order-create flow keys off `email` and
the order-status flow trusts `order_number` as the sole credential
(same posture as a Stripe / PayPal session reference).

| Method | Path | Query params | Auth | Cache TTL |
|---|---|---|---|---|
| `GET` | `/api/v1/public/games` | — | none | 300s |
| `GET` | `/api/v1/public/services` | `game`, `platform`, `featured`, `search`, `page`, `page_size` | none | 180s |
| `GET` | `/api/v1/public/services/{slug}` | — | none | 180s |
| `GET` | `/api/v1/public/reviews` | `service_id`, `featured` | none | 600s |
| `POST` | `/api/v1/public/orders` | — | none | — |
| `GET` | `/api/v1/public/orders/{order_number}/status` | — | `order_number` is the credential | — |
| `POST` | `/api/v1/public/orders/{order_number}/claim-payment` | — | `order_number` is the credential | — |
| `POST` | `/api/v1/public/contact` | — | none (rate-limited: 5/min/IP) | — |
| `POST` | `/api/v1/payments/webhooks/ecomtrade24` | — | `X-EcomTrade24-Signature` (HMAC-SHA256) | — |

### Query-param constraints

| Param | Allowed values |
|---|---|
| `game` | slug: `^[a-z0-9]+(-[a-z0-9]+)*$`, max 100 chars |
| `platform` | `ps` / `xbox` / `pc`, **case-insensitive** (`PS`, `Pc` accepted) |
| `search` | 2–100 chars; substring match across `title` + `description` |
| `page` | 1–10000 |
| `page_size` | 1–100 |

Bad input → **HTTP 422** with Pydantic validation detail; never
silently coerced. See [Error response format](#5-error-response-format).

---

## 3. Admin endpoints (high-level)

All admin routes require `Authorization: Bearer <JWT>`. JWT comes
from `POST /api/v1/auth/login`.

| Prefix | Surface | Min role |
|---|---|---|
| `/api/v1/auth/*` | `POST /login`, `POST /refresh`, `GET /me`, `POST /logout` | none (login) / any (me/logout) |
| `/api/v1/users/*` | CRUD users | superadmin |
| `/api/v1/games/*` | CRUD games + reorder | any read · manager+ write · admin+ delete |
| `/api/v1/services/*` | CRUD services + nested options + reorder | any read · manager+ write · admin+ delete |
| `/api/v1/orders/*` | List, status change, stats | viewer+ read · manager+ status change |
| `/api/v1/reviews/*` | CRUD reviews + reorder | any read · manager+ write · admin+ delete |
| `/api/v1/uploads` | `POST` multipart, served via `/uploads/*` | manager+ |
| `/api/v1/dashboard/*` | KPIs | viewer+ |

Full per-endpoint shape lives in the [OpenAPI snapshot](openapi-snapshot.json).

### Roles (lowest → highest)

`viewer` → `manager` → `admin` → `superadmin`

---

## 4. Response models (TypeScript shapes)

Authoritative shapes live in the OpenAPI snapshot. The TypeScript
sketches below cover the public payloads the storefront cares about.

```ts
type Game = {
  id: string;                                  // UUID
  slug: string;
  name: string;
  description: string | null;
  image_desktop_url: string | null;
  image_mobile_url: string | null;
  status: "active" | "coming_soon" | "hidden";
  service_count: number;                       // active+non-deleted services
};

type Service = {
  id: string;
  slug: string;
  title: string;
  platform: "ps" | "xbox" | "pc";
  image_desktop_url: string | null;
  image_mobile_url: string | null;
  image_alt: string | null;
  description: string[];                       // paragraph array
  what_you_get: Array<{ title: string; lead: string; items: string[] }>;
  sections: Array<{ title: string; texts: string[] }>;
  seo_title: string | null;
  seo_description: string | null;
  is_featured: boolean;
  options: ServiceOption[];
};

type ServiceOption = {
  id: string;
  label: string;
  price_usd: number;                           // 2-decimal
  price_eur: number;
  is_default: boolean;
  sort_order: number;
};

type Review = {
  id: string;
  author_name: string;
  rating: number;                              // 1..5
  text: string;
  is_featured: boolean;
  service: { slug: string; title: string; platform: string } | null;
  created_at: string;                          // ISO-8601
};

type PublicOrderItemCreate = {                   // POST /api/v1/public/orders → items[]
  service_slug: string;                          // URL-friendly, NOT the UUID
  option_id: string;                             // UUID — option lookup is by PK
  qty: number;                                   // 1..100, required (no default)
  // extra='forbid' — unknown fields (e.g. legacy `service_id` / `quantity`)
  // reject with 422 instead of being silently dropped.
};

type PublicOrderResponse = {
  order_number: string;
  status: "pending" | "paid" | "in_progress" | "completed" | "cancelled" | "refunded";
  final_total_usd: number;                     // always present, server-computed
  final_total_eur: number | null;              // EUR snapshot at order creation
  discount_amount_usd: number | null;          // 5% for USDT_TRC20, 0 otherwise
  display_currency: "USD" | "EUR";
  created_at: string;
  checkout_url: string | null;                 // present for hosted-checkout providers
};

type PaymentClaimResponse = {                    // POST .../claim-payment
  order_number: string;
  status: PublicOrderResponse["status"];          // always "pending" on first claim
  payment_claimed_at: string | null;              // ISO-8601, null if claim wasn't filed
};

type PublicOrderStatusResponse = {
  order_number: string;
  status: PublicOrderResponse["status"];
  paid_at: string | null;
  final_total_usd: number;
  final_total_eur: number | null;
  display_currency: "USD" | "EUR";
  last_updated_at: string;                     // ISO-8601, see "Polling" below
};

type ContactSubmissionCreate = {                 // POST /api/v1/public/contact
  preferred_contact: "discord" | "telegram" | "whatsapp" | "email";
  handle: string;                                // 1..200 chars, trimmed
  email?: string | null;                         // required if preferred_contact === "email"
  message: string;                               // 10..2000 chars, trimmed
};

type ContactSubmissionResponse = {
  status: "ok";                                  // PII-free success signal
};
```

---

## 4.0. Manual-payment claim flow

Hosted-checkout providers (e.g. EcomTrade24) update order status via
webhook — the storefront just polls `/status` and shows the result.
PayPal and USDT (TRC20) are **manual**: the buyer pays into our
wallet / PayPal outside the API. The success page asks them to confirm
with a button that hits:

```
POST /api/v1/public/orders/{order_number}/claim-payment
```

Body: empty. Response: [`PaymentClaimResponse`](#4-response-models-typescript-shapes).

**Semantics**
- Sets `payment_claimed_at = now()` on the order.
- Status stays `pending`. Only admin verification (from the admin panel)
  flips it to `paid` and sets `paid_at`.
- Fires a Telegram alert to the admin so they can verify the wallet /
  PayPal balance.
- **Idempotent**: a replayed call (offline blip, double-click, FE retry)
  returns the original `payment_claimed_at` and does **not** re-notify.

**Errors**
- `400` — order's `payment_method` isn't manual (e.g. `card_ecomtrade24`).
  Hosted-checkout providers must not flow through this endpoint, since
  the webhook handles the same transition with provider signature.
- `404` — order_number does not exist.

After a successful claim, the storefront returns to the polling loop
described in §4.1 — the admin's manual verification surfaces as
`status: "paid"` on the next `GET /status` call.

---

## 4.1. Order status polling contract

The payment-success page polls `GET /api/v1/public/orders/{order_number}/status`
until the order leaves `pending` (i.e. webhook landed) or the budget runs out.

| Knob | Value | Why |
|---|---|---|
| Poll interval | **5 seconds** | Tight enough that the success page feels responsive without hammering the API |
| Max attempts | **36** | 5 s × 36 = **180 s** total budget — covers the long tail of provider webhook delivery (P99 < 90 s for EcomTrade24) |
| Stop condition | `status !== "pending"` | Any terminal state (`paid`, `cancelled`, …) → show the matching UI |
| Timeout fallback | After attempt 36 | Show "still processing" UI + manual refresh CTA + support contact |

`last_updated_at` lets the client detect "nothing changed since last
poll" cheaply — compare against the previous response, skip re-rendering
unchanged sections. It sources from `payment_status_updated_at` when a
gateway has nudged the order, otherwise from `updated_at`.

The endpoint is **not rate-limited** server-side at this scale; if abuse
becomes a problem, the Cloudflare layer ahead of FastAPI is where we'd
add a per-`order_number` cap. Don't bypass the agreed interval — that's
a load contract, not a hard ceiling.

---

## 5. Error response format

| Status | Shape | When |
|---|---|---|
| `400` | `{"detail": "<message>"}` | Domain rule violation (e.g. invalid upload folder, bad order transition) |
| `401` | `{"detail": "<message>"}` | Missing / invalid JWT |
| `403` | `{"detail": "<message>"}` | Authenticated but lacks the required role |
| `404` | `{"detail": "<message>"}` | Resource missing OR **route not registered** (check the URL prefix) |
| `409` | `{"detail": "<message>", "message": "<details>"}` | Conflict (duplicate slug, FK violation) |
| `422` | `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}` | Pydantic validation failure (any query/path/body field) |
| `429` | `{"detail": "<message>"}` | Rate-limited (e.g. `/public/contact` accepts 5/min/IP). Retry after the window resets. |
| `5xx` | `{"detail": "Internal server error"}` | Generic — full traceback in server logs, correlate via `X-Request-ID` |

Pydantic `422` is **always** returned for malformed input — clients
should never see a `500` for a query-param typo. If they do, that's
a backend bug.

---

## 6. Standard headers

| Header | Direction | Purpose |
|---|---|---|
| `Authorization: Bearer <JWT>` | Request | Admin auth (every `/api/v1/*` except `/auth/login`, `/public/*`, `/payments/webhooks/*`) |
| `X-EcomTrade24-Signature` | Request (webhook) | HMAC-SHA256 of raw body; verified against `ECOMTRADE24_WEBHOOK_SECRET` |
| `X-Request-ID` | Request (optional) **and** Response | Tracing. Inbound value is preserved so distributed traces correlate; server mints a UUID hex if none supplied. |
| `X-Cache: HIT \| MISS \| BYPASS` | Response (public reads) | `HIT` = served from Redis, `MISS` = computed and stored, `BYPASS` = Redis unavailable, served from DB |
| `Cache-Control: public, max-age=31536000, immutable` | Response (uploads only) | Content-hashed filenames make long-lived caching safe |
| `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy` | Response (all) | Security baseline, mirrors the storefront's Vercel defaults |
| `Access-Control-Allow-*` | Response | CORS, configured via `CORS_ORIGINS` env |

---

## Breaking change protocol

A **breaking change** is any modification that requires the
storefront, admin panel, or webhook caller to update:

- removing or renaming an endpoint / route
- changing a response shape (removing a field, changing a type)
- adding a new **required** query param or request-body field
- changing auth requirements
- tightening validation in a way existing clients would fail

### Process

1. **PR title MUST start with `[BREAKING]`** — visible signal in the
   PR list and in the changelog.
2. **PR description MUST include:**
   - Affected endpoints (full paths)
   - Migration plan for each client repo (FE storefront, admin panel,
     webhook integrators)
   - Rollout strategy: parallel versioning vs. big-bang
3. **Manager (Murodulla) review required** — they coordinate the
   client-side TZs.
4. **Default strategy: URL versioning.** New `/api/v2/...` ships
   alongside the existing `/api/v1/...`. Old version stays live for
   **3 months** to give clients time to migrate.
5. **Big-bang migration is only allowed when** FE + admin + every
   webhook integrator can deploy simultaneously **and** Manager
   approves explicitly.

### Communication checklist (paste into the PR description)

```markdown
- [ ] PR title starts with `[BREAKING]`
- [ ] Affected client repos listed: <storefront / admin / integrators>
- [ ] Manager notified before merge
- [ ] Client-side TZ written and assigned (if migration needed)
- [ ] Migration deadline communicated
- [ ] OpenAPI snapshot regenerated
```

### Drift guard

Two layers, run on every PR:

1. **Schema** — CI regenerates the OpenAPI snapshot from the live app
   and diffs against the committed `docs/openapi-snapshot.json`. Any
   route or `response_model` change without a snapshot refresh fails
   the build with the exact diff.
2. **Runtime** — Contract tests in `tests/contracts/` verify response
   shape on every CI run. They snapshot the key+type skeleton of each
   public endpoint, so removing a field, retyping one, or adding one
   surfaces as a failing test with a clean diff. Catches behaviour
   the schema can't see (`response_model_exclude`, computed fields).

   ```
   E   -     'service_count': 'int',
   ```

Manager + reviewers see contract changes in PR review every time —
not weeks later when a client breaks in production.

To regenerate locally:

```bash
python -m scripts.dump_openapi_snapshot       # OpenAPI schema
git add docs/openapi-snapshot.json

uv run pytest tests/contracts/ --snapshot-update    # runtime shapes
git add tests/contracts/__snapshots__/
```

---

## Tracing a production incident

When a client reports an unexpected 4xx / 5xx:

1. Grab the `X-Request-ID` from the failing response.
2. Search Railway logs for that ID — every line of that request
   carries it (structlog contextvars).
3. Look at `event=request_completed` for the status + duration.
4. If 5xx, the matching `event=request_failed` carries the full
   traceback.
5. Cross-reference with this contract: was the URL right? Was the
   query param shape right? See sections 2, 5, 6.

If after that the behaviour still doesn't match this contract — file
a bug, that's a real regression.
