# Multi-tenant jobOS Hub

Canonical state is **PostgreSQL + a BlobStore**, not git. The Hub process is stateless: restarting it does not drop tenant work.

## Modules, Interfaces, Seams, Adapters

| Module | Interface | Depth | Adapters |
| --- | --- | --- | --- |
| Account | `AccountService.signup/login` + `TenantContext` | Password KDF, account id mint, reserved names | Postgres `accounts` |
| JobStore | `BoardDB.list_jobs/get_job/insert_job/... (tenant, …)` | Dedup, events, status counts | Postgres `jobs`/`events` |
| Queue | `QueueService` claim/ack + `QueueBus.publish/get` | Leases, dedupe, `{account_id}.{kind}` routing | Postgres rows + **RabbitMQ** (prod) / **MemoryQueueBus** (tests) |
| BlobStore | `put/get/delete(tenant, key)` | Path safety, metadata sidecar | **FilesystemBlobStore** (prod, volumized) / **MemoryBlobStore** (tests) |
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

SQL and blob keys are namespaced by `account_id`. Queue routing keys are `{account_id}.{kind}` on exchange `jobos.work`, bound to `jobos.t.{account_id}`. Tenant A cannot list Tenant B jobs, files, skills, memory, or queue items.

## Run locally

```bash
docker compose up -d --build
# Hub http://127.0.0.1:8787
# Postgres + RabbitMQ + blob named volume
```

Open `/`, then `/login`, create two usernames, confirm each board is empty of the other's jobs.

Env (gitignored `.env`, see `.env.example`):

- `DATABASE_URL` — Postgres
- `AMQP_URL` + `QUEUE_ADAPTER=rabbitmq` — production queue
- `BLOB_ROOT` + `BLOB_ADAPTER=filesystem` — resumes/files
- Tests use in-memory queue + blob Adapters (`QUEUE_ADAPTER=memory`, `BLOB_ADAPTER=memory`)

Git `ledger/` is **export-only** (`GET /api/export/ledger`), not the live list.
