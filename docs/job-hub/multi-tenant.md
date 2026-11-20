# Multi-tenant jobOS Hub

Canonical state is **PostgreSQL + a BlobStore**, not git. The Hub process is stateless: restarting it does not drop tenant work.

## Modules, Interfaces, Seams, Adapters

| Module | Interface | Depth | Adapters |
| --- | --- | --- | --- |
| Account | `AccountService.signup/login` + `TenantContext` | Password KDF, account id mint, reserved names | Postgres `accounts` |
| JobStore | `BoardDB.list_jobs/get_job/insert_job/... (tenant, …)` | Dedup, events, status counts | Postgres `jobs`/`events` |
| Queue | claim / ack / nack | Leases, dedupe | Postgres `queue_items`. The in-memory store is the driver when `DATABASE_URL` is empty. |
| BlobStore | `put/get/delete(account, key)` | Path safety, metadata sidecar | memory, filesystem volume, or any S3-compatible store (MinIO in Compose) |
| Session | cookie `hub_session` + `X-CSRF` | Idle expiry, CSRF on cookie writes | Postgres `sessions` |

**TenantContext is required** on production data paths. Handlers pass `principal.tenant`; stores enforce `account_id`. Do not sprinkle `if tenant:` in Hub routes.

Alternatives considered for the Tenant+Store+Queue cluster:

1. **Required `TenantContext` on every store method** (chosen). Small Interface, testable, Locality in the store. Leverage: deleting the Module would reintroduce `account_id` filters in every caller.
2. Per-request store objects with tenant baked in. More object churn; same Depth, worse Locality for scripts.
3. Postgres RLS only. Hides the Interface from tests and from the Memory/Filesystem Adapters.

One Adapter is a hypothetical Seam. Queue and Blob each have **two** Adapters so the Seam is real. An S3 Adapter can sit on `BlobStore` later without rewriting callers.

## Auth

- Public landing: `GET /`
- Login + signup: `GET /login`, `POST /api/auth/signup`, `POST /api/auth/login`
- Username + password. **No dashboard token** for signup/login. Argon2 KDF.
- Each account gets `acc_…`. Tracks are copied onto the account at signup.
- Session cookies are httpOnly. Browser writes send `X-CSRF` matching `hub_csrf`.
- Compat `X-Role` + `X-Token` still maps to a reserved `acc_compat` tenant so existing agent tests keep working. Prefer session or `Authorization: Bearer` keys.

One-time `POST /api/auth/bootstrap` remains for the first operator on a fresh deploy (email + bootstrap token). After that, anyone may `signup` with a username.

## Isolation

SQL and blob keys are namespaced by `account_id`. Queue rows carry the same account id. Live updates on `GET /api/stream` and `GET /ws` are fanned out per account. Tenant A cannot list Tenant B jobs, files, skills, memory, or queue items.

## Run locally

```bash
docker compose up -d --build
# SPA http://127.0.0.1:8080
# API http://127.0.0.1:8081
# optional: --profile data --profile cache --profile blobs
```

Open `/`, then `/login`, create two usernames, confirm each board is empty of the other's jobs.

Env (gitignored `.env`, see `.env.example`):

- `DATABASE_URL` — Postgres. Empty means the in-memory store.
- `REDIS_URL` — optional cache. Empty means the cache stays off unless `CACHE_DRIVER=memory`.
- `BLOB_DRIVER` — `memory`, `filesystem` (`BLOB_ROOT`), or `s3` (`S3_ENDPOINT`, `S3_BUCKET`, keys).
- `HUB_PLUGINS=auto` fills those when the hostnames `postgres`, `redis`, or `minio` resolve.

Git `ledger/` is **export-only** (`GET /api/export/ledger`), not the live list.
