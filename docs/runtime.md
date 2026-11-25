# Runtime

jobOS Hub is two containers.

| Container | Code | Role |
| --- | --- | --- |
| `web` | `web/` | React SPA. No server render. nginx proxies `/api`, `/ws`, `/health`, `/llms.txt`, `/agents.txt`, and `/a2a` to the API. |
| `api` | `server/` | Go + Gin. Jobs, auth, queue, skill and MCP registry, memory, presence, onboarding packs. |

RabbitMQ is not part of this runtime. Work leases live in the `queue_items` table. `POST /api/queue/claim` and `POST /api/presence/heartbeat` include a compact memory recall for that beat. Live updates use `GET /api/stream` (SSE) and `GET /ws` (WebSocket).

## Drivers

| Concern | Off | On |
| --- | --- | --- |
| Database | empty `DATABASE_URL` → in-memory store | Postgres (`--profile data` or any `DATABASE_URL`) |
| Cache | empty `REDIS_URL` and `CACHE_DRIVER` unset → nop | `REDIS_URL` selects Redis. `CACHE_DRIVER=memory` is the single-process cache. Job lists (15s), API keys and sessions (2m, dropped when a key is rotated or a user is disabled), the candidate flag (60s), and heartbeat recall cards (10s) stay off the database until a write drops them. |
| Blobs | empty `BLOB_DRIVER` → memory | `filesystem` (`BLOB_ROOT`, persisted on the `blobs` volume) or `s3` (MinIO and any other S3 API). An empty value lets the `blobs` profile select MinIO. Resume PDFs and candidate YAML go through this seam. |

```bash
docker compose up -d --build
docker compose --profile data --profile cache --profile blobs up -d --build
```

### Database migrations (manual)

The Hub process **does not** migrate Postgres on boot. Apply schema yourself before (or instead of) deploying a revision that needs new tables/indexes:

```bash
# local / CI
DATABASE_URL='postgres://…' bash scripts/hub_migrate.sh
# or
DATABASE_URL='postgres://…' go run ./cmd/hub migrate   # from server/

# Compose one-shot (same image as hub)
docker compose --profile migrate run --rm migrate

# Cloud Run Job (same image as the service, args: migrate)
# gcloud run jobs execute jobos-migrate --region=…
```

Boot fails fast with `database schema missing; run: hub migrate` when `accounts` is absent. Idempotent repair statements (column copies, bool coercion, remapping cross-account skill ids) live in the same `hub migrate` path.

`HUB_PLUGINS` defaults to `auto` in Compose. When `postgres`, `redis`, or `minio` resolves on the API network, the empty driver switches to that service: Postgres at `postgres:5432`, Redis at `redis:6379`, and MinIO at `http://minio:9000` with bucket `jobos`. The API creates the bucket on startup and retries Postgres until it accepts connections. Set `DATABASE_URL`, `REDIS_URL`, or `BLOB_DRIVER` to keep a driver you chose yourself. Set `HUB_PLUGINS=off` to leave every optional service unused even when it is running.

The API image is built from the repo root (`dockerfile: server/Dockerfile`) and ships `skills/`, `docs/`, `mcp/`, `scripts/`, `handoffs/`, and `AGENTS.md` at `HUB_REPO_ROOT=/opt/jobos`, so onboarding works without a bind mount.

The SPA is `http://127.0.0.1:8080`. The API is also on `http://127.0.0.1:8081` for agents that should not go through nginx.

`GET /health` reports `store`, `cache`, `blob`, and `"rabbitmq": false`. It also reports `admin_bootstrapped`, `candidate_onboarded`, `resume_present`, `ready_for_agents`, and `next_step` (`signup`, `onboarding`, `resume`, or `ready`) for the earliest admin account. `GET /api/candidate/status` returns the same candidate fields.

Onboarding files come from `HUB_REPO_ROOT`. `GET /api/onboarding` returns the track contract: process rules, reading URLs with sha256, skill file URLs, connectors, queues, and the memory endpoints. `GET /api/packs/current/skills.zip` zips those skill folders. `GET /api/docs/*`, `GET /api/skills/:name/*`, `GET /api/mcp/example.json`, `GET /api/mcp/hosted/:name.json`, and `GET /api/scripts/:name` serve the same tree. Discovery agents only receive discovery skills; admin and maintenance receive every skill. `POST /api/packs/rebuild` (admin or maintenance) re-seeds skills and MCPs.

`GET /api/registry/mcps` lists connectors seeded from `mcp/mcp.example.json` when the repo root is set. `POST /api/registry/skills/:id/fork` copies a skill into the caller's local scope.

Memory writes are capped inside a 15 minute window: 6 on a worker pod, 3 on a track pod, 2 on common. Titles and bodies are length-checked, dumps and hub keys are rejected, and worker notes expire after 7 days unless pinned. `GET /api/memory/recall?q=` matches title, body, and company. On Postgres that filter is a `simple` full-text query (up to eight tokens, AND) backed by a GIN index. `POST /api/memory/items/:id/move` copies or moves a note between pods. Passwords are argon2id (compatible with the former Python Hub hashes). A bcrypt hash from an earlier Go account still logs in. `POST /api/auth/bootstrap` consumes `HUB_BOOTSTRAP_TOKEN` once and opens an admin session. `GET /api/a2a/directory` lists the local agent cards plus saved peers.
