# Runtime

jobOS Hub is two containers.

| Container | Code | Role |
| --- | --- | --- |
| `web` | `web/` | React SPA. No server render. nginx proxies `/api`, `/ws`, `/health`, `/llms.txt`, `/agents.txt`, and `/a2a` to the API. |
| `api` | `server/` | Go + Gin. Jobs, auth, queue, skill and MCP registry, memory, presence, onboarding packs. |

RabbitMQ is not part of this runtime. Work leases live in the `queue_items` table. Live updates use `GET /api/stream` (SSE) and `GET /ws` (WebSocket).

## Drivers

| Concern | Off | On |
| --- | --- | --- |
| Database | empty `DATABASE_URL` → in-memory store | Postgres (`--profile data` or any `DATABASE_URL`) |
| Cache | empty `REDIS_URL` and `CACHE_DRIVER` unset → nop | `REDIS_URL` selects Redis. `CACHE_DRIVER=memory` is the single-process cache. Job lists are cached for 15s and dropped on writes. |
| Blobs | `BLOB_DRIVER=memory` | `filesystem` (`BLOB_ROOT`) or `s3` (MinIO and any other S3 API). Resume PDFs and candidate YAML go through this seam. |

```bash
docker compose up -d --build
docker compose --profile data --profile cache --profile blobs up -d --build
```

With the data, cache, and blobs profiles, set:

```bash
DATABASE_URL=postgres://jobos:jobos@postgres:5432/jobos?sslmode=disable
REDIS_URL=redis://redis:6379/0
BLOB_DRIVER=s3
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=jobos
S3_SECRET_KEY=jobossecret
S3_BUCKET=jobos
```

Create the MinIO bucket once (`mc mb local/jobos` or the MinIO console on port 9001). The API does not create buckets.

The SPA is `http://127.0.0.1:8080`. The API is also on `http://127.0.0.1:8081` for agents that should not go through nginx.

`GET /health` reports `store`, `cache`, `blob`, and `"rabbitmq": false`.

Onboarding files come from `HUB_REPO_ROOT`. `GET /api/onboarding` lists the track's skills and readings. `GET /api/packs/current/skills.zip` zips those skill folders. `GET /api/docs/*`, `GET /api/skills/:name/*`, `GET /api/mcp/example.json`, and `GET /api/scripts/:name` serve the same tree. Discovery agents only receive discovery skills; admin and maintenance receive every skill. `POST /api/packs/rebuild` (admin or maintenance) re-seeds skills and MCPs.

`GET /api/registry/mcps` lists connectors seeded from `mcp/mcp.example.json` when the repo root is set. `POST /api/registry/skills/:id/fork` copies a skill into the caller's local scope.

Memory writes are capped inside a 15 minute window: 6 on a worker pod, 3 on a track pod, 2 on common. Bodies are length-checked and rejected when they contain a hub key.
