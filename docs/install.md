# Install and host jobOS Hub

jobOS Hub is the live coordination plane for the job harness. The current Compose file runs two containers: a Go API and a React SPA. Postgres, Redis, and MinIO are optional profiles. RabbitMQ is not in that file. See [`docs/runtime.md`](runtime.md). Agents do **not** clone this repo. They curl `$HUB_URL/llms.txt` and `$HUB_URL/agents.txt`.

`scripts/hub_deploy.sh` starts the Go API and serves the built React SPA on port 8787. `board/docker-compose.yml` and the repo-root Compose files run the API and the SPA as separate containers. Traefik also answers on port 8787 and sends that traffic to the SPA.

**Onboarding is the first thing you do after the process is up.** Until a truthful candidate profile exists, jobs, invites, queues, messages, and A2A sends return `409 candidate_required`. Do not copy `profiles/candidate.example.yaml` into production.

Full operator API: [`docs/job-hub/human.md`](job-hub/human.md). Agents: [`docs/job-hub/agent.md`](job-hub/agent.md). A2A: [`docs/job-hub/a2a.md`](job-hub/a2a.md).

## Pick an install

| How | When | Command |
| --- | --- | --- |
| **Docker Compose** | Laptop or VM. SPA on 8080, API on 8081 | `docker compose up -d --build` |
| **Compose + data profiles** | Postgres, Redis, and MinIO on the same network | `docker compose --profile data --profile cache --profile blobs up -d --build` |
| **Compose, Postgres always on** | Same API and SPA, Postgres is not a profile | `docker compose -f docker-compose.plain.yml up -d --build` |
| **Docker Compose + Traefik** | Public host, ports 80/443/8787 | `HUB_PUBLIC_HOST=your.host bash scripts/hub_docker.sh` |
| **`docker build` / `docker run`** | One container, no Compose | See [Docker (no Compose)](#docker-no-compose) |
| **uv / bare metal** | Cursor Cloud, no Docker | `bash scripts/hub_deploy.sh` |
| **Coolify** | Self-hosted PaaS, Compose from GitHub | [`docs/coolify.md`](coolify.md) — named volumes, no `${...}` in volume sources |
| **Push to `main`** | This OCI host (Traefik + Hub already up) | [Deploy on push](deploy.md) |

Docker Desktop, Engine 24+, or Compose v2 is enough. Traefik is **optional**. This GitHub repo deploys to the hunt machine on every push to `main` — see [`docs/deploy.md`](deploy.md). Feature screenshots: [`docs/demo/README.md`](demo/README.md).

## First-run sequence (every install)

1. Start the Hub (one of the commands above).
2. Open `/` (landing) then `/login`. Create a username + password. **No dashboard token.** First-boot still has `/admin/signup#bootstrap=jh_boot_…` for the very first operator on a fresh database; after that, anyone may sign up. Public get-started (no login): `/start`.
3. You are sent to **`/onboarding`**. Fill identity, titles, locations, and (recommended) a resume PDF. The example “Ada Example” profile is rejected.
4. Health `next_step` becomes `ready` (or `resume` if you skipped the PDF).
5. Mint track invites at `/admin`. Share join URLs out of band. Agents fetch `/.well-known/agent-card.json` for A2A.

Until step 3 is done:

```bash
curl -sS "$HUB_URL/health"
# candidate_onboarded: false
# next_step: onboarding   (or signup)

curl -sS -X POST "$HUB_URL/api/jobs" -H "X-Role: discovery" ...
# 409 {"detail":{"code":"candidate_required","onboarding_url":"/onboarding"}}
```

## Docker Compose

Two containers. The SPA is `http://127.0.0.1:8080`. The API is also on `http://127.0.0.1:8081`. `docker compose up` does not start Postgres, Redis, or MinIO. Add `--profile data`, `--profile cache`, and `--profile blobs` when you want them. `HUB_PLUGINS=auto` attaches a driver when that hostname resolves. Filesystem blobs use the named volume `blobs`. Postgres uses `pgdata`. There is no RabbitMQ volume. Volume sources are named volumes (no `${...}`, no `~`) so Coolify continuous deploys keep data — see [`docs/coolify.md`](coolify.md). Driver details: [`docs/runtime.md`](runtime.md).

```bash
cd /path/to/jobos
export HUB_PUBLIC_URL=http://127.0.0.1:8080
docker compose up -d --build
docker compose logs -f api web
```

Open `http://127.0.0.1:8080/login`. After signup, `/onboarding`. Board UI is `/board`.

### Outside Postgres

The bundled `postgres` service starts only with `--profile data`. The API uses `DATABASE_URL` when that variable is set. When it is empty and `HUB_PLUGINS=auto`, the API fills a URL if the hostname `postgres` resolves.

To use a Postgres that this stack does not create, set secret `DATABASE_URL` (Coolify or Railway environment, repo-root `.env`, or the shell). Compose passes that value through. Leave it unset to use the bundled service.

From inside the Hub container, Postgres on the Docker host is `host.docker.internal`, not `127.0.0.1`. Put `sslmode` in the URL when the server requires TLS. Bare metal still reads `DATABASE_URL` from `board/.env`.

```bash
DATABASE_URL='postgresql://user:pass@db.example:5432/jobos?sslmode=require' \
  docker compose up -d --build
```

When `DATABASE_URL` is empty and `HUB_PLUGINS=auto`, the API uses `JOBOS_PG_USER`, `JOBOS_PG_PASSWORD`, and `JOBOS_PG_DB` against host `postgres`. The bundled image initializes user and database `jobos`.

Stop: `docker compose down` (keeps named volumes). Destroy data: `docker compose down -v`.

Browser e2e (Playwright against Compose Hub): `bash scripts/e2e_browser.sh`. Inventory: [`e2e/FLOWS.md`](../e2e/FLOWS.md).

## Docker Compose + Traefik (public host)

Ports **80**, **443**, and **8787** all reach the SPA. The SPA proxies the API. Board is `/board`. File-based Traefik config (no Docker socket): `traefik/traefik.yml`, `traefik/dynamic.yml`.

```bash
# hostname, IPv4, or IP:port. :443 → https:// on invite URLs.
HUB_PUBLIC_HOST=hunt.example.com bash scripts/hub_docker.sh
# uses docker-compose.traefik.yml
# or
HUB_PUBLIC_HOST=12.234.244.34 docker compose -f docker-compose.traefik.yml up -d --build
```

Put a real TLS certificate in front if you need one (Traefik `websecure` already terminates TLS with a default cert; replace with Let’s Encrypt or a load-balancer cert in production). Do not put tokens in the public origin.

## Coolify

Coolify has no universal one-click URL. Create a **Docker Compose** resource pointed at this GitHub repo. Full notes (including why volume sources cannot use `${...}`): [`docs/coolify.md`](coolify.md).

1. Source: `https://github.com/unownone/jobos` (branch `main`).
2. Compose file: `docker-compose.yml` (Go API + React SPA). Postgres, Redis, and MinIO are profiles. Do not invent a second stack.
3. Set `HUB_PUBLIC_URL` to the Coolify FQDN, e.g. `https://hub.example.com`.
4. Confirm Persistent Storage lists named volumes `pgdata` and `blobs` (Coolify prefixes them). Do not convert them to `${...}` or `~` binds.
5. After first boot, open `/login`, then `/onboarding`. Healthcheck is `GET /health` on port 8080 inside the API container.

The Railway button builds the root `Dockerfile`, which is the Go API serving the SPA from the same container. Local and Coolify Compose build `server/Dockerfile` and `web/Dockerfile` as two containers.

## Railway

Use the README **Deploy on Railway** button (`railway.json` + `Dockerfile`). Railway injects `PORT`. The process binds that port. Compose remains the two-container layout.

Set after the first domain exists:

```bash
HUB_PUBLIC_URL=https://<your-railway-domain>
HUB_PUBLIC_HOST=<your-railway-domain>
JOBOS_NONINTERACTIVE=1
```

Provide `DATABASE_URL` to PostgreSQL (Railway plugin or a private instance). Do not publish Postgres. Healthcheck path is `/health`. Do not require `ready_for_agents` for the probe — that stays false until onboarding.

## Docker (no Compose)

```bash
docker build -t jobos-hub .
# Compose is the supported path (Hub + internal Postgres). A lone
# `docker run` needs DATABASE_URL to a Postgres that is not published
# to the internet, plus the same env as docker-compose.yml.
```

Compose is required for a full install. The Hub image is stateless.

## Bare metal

This path starts the Go API and serves `web/dist`. It still uses `uv` to mint the one-time bootstrap token. Needs Go, Node, and [`uv`](https://docs.astral.sh/uv/).

```bash
bash scripts/setup_uv.sh          # if uv is missing
export HUB_PUBLIC_HOST=127.0.0.1:8787
bash scripts/hub_deploy.sh
```

Listens on `0.0.0.0:8787` and serves the SPA from that same port. Secrets: gitignored `board/.env` and `board/tokens.local.json`. Set `DATABASE_URL` to PostgreSQL. Dry run: `HUB_DEPLOY_DRY_RUN=1 bash scripts/hub_deploy.sh`.

## Reverse proxy / TLS

Plain Compose publishes the SPA on 8080. For a hostname:

- **Caddy** (example): `hunt.example.com { reverse_proxy 127.0.0.1:8080 }`
- **nginx**: `proxy_pass http://127.0.0.1:8080;` and forward `Upgrade` for `/ws`
- **Cloudflare Tunnel / Tailscale**: point at 8080; set `HUB_PUBLIC_URL` to the public origin so invite links work
- **Traefik template**: repo-root `docker-compose.traefik.yml`

Always set `HUB_PUBLIC_URL` (or `HUB_PUBLIC_HOST`) to the origin browsers and agents actually use. Never put `jh_boot_` / `jh_agt_` / `BOARD_TOKEN_*` in that URL.

## Persistence and backups

The Hub container stores nothing durable on disk. PostgreSQL is the database.

| Where | What |
| --- | --- |
| Postgres (bundled Compose service, or `DATABASE_URL` from secrets) | Jobs, users, sessions, queue, messages, A2A, memory pods, candidate YAML, resume PDF, bootstrap token, token-burn metrics |
| `/tmp/jobos-packs/` in Hub | Skill/MCP zip snapshots (rebuilt on start) |
| Named volume `pgdata` | Postgres files, when the `data` profile is running |
| Named volume `blobs` | Resume PDFs and other filesystem blob files |
| Named volume `minio` | MinIO data, when the `blobs` profile is running |

Backup the database Hub is actually using.

- Bundled Compose service: stop Postgres and copy the `pgdata` volume, or `pg_dump` from the Hub network.
- `DATABASE_URL` points at a database this stack does not create: back up that database. `pgdata` is the unused bundled instance.

Airgap export for git: admin `GET /api/export/ledger`.

Postgres is **not** published on the host. Do not add a `ports:` mapping for it.

## Health

```bash
curl -sS "$HUB_URL/health"
curl -sS "$HUB_URL/ready"
curl -sS "$HUB_URL/llms.txt"
curl -sS "$HUB_URL/agents.txt"
```

Public JSON, no secrets. Fields: `ok`, `admin_bootstrapped`, `candidate_onboarded`, `resume_present`, `ready_for_agents`, `next_step` (`signup` \| `onboarding` \| `resume` \| `ready`).

Liveness: `/health`. Do not require `ready_for_agents` for container health or the box never becomes healthy before you onboard.

## A2A (other agent runtimes)

After onboarding, any A2A client can:

```bash
curl -sS "$HUB_URL/.well-known/agent-card.json"
curl -sS -X POST "$HUB_URL/a2a" \
  -H "Authorization: Bearer $HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"role":"user","messageId":"m1","parts":[{"kind":"text","text":"packet ready","data":null},{"kind":"data","data":{"type":"handoff","to_track":"application"}}]}}}'
```

See [`docs/job-hub/a2a.md`](job-hub/a2a.md).

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Signup page says admin already exists | Log in at `/login`. There is no second bootstrap. |
| `409 candidate_required` | Finish `/onboarding`. Example Ada Example YAML is rejected. |
| Invite URLs point at 127.0.0.1 | Set `HUB_PUBLIC_HOST` / `HUB_PUBLIC_URL` to the public origin and recreate the container. |
| Agents invent a candidate | Hub `candidate.present` is false — they must stop. |
| Lost admin password | Restore the `pgdata` volume from backup. Do not invent `candidate.yaml` to “unblock”. |
| Coolify: `Invalid volume source: contains forbidden character '${'` | Volume sources must be named volumes, not `${VAR:-...}` binds. See [`docs/coolify.md`](coolify.md). |
| Coolify redeploy emptied Postgres | Bind mounts under `~` or `/artifacts` reset each deploy. Use named volumes. |
| Docker healthcheck failing | `docker compose logs api`. `/health` must answer on port 8080 inside the API container. |
| Traefik 404 | Confirm `traefik/dynamic.yml` service URL is `http://web:80` and the `web` service is healthy. |

## Deploy on push (this host)

GitHub `unownone/jobos` is origin. A push to `main` rebuilds Job Hub on the OCI box (`/home/opc/jobos-live`, Docker Compose, named volumes `pgdata` / `blobs`). Pull requests run **Deploy check** first (SSH wiring; no ship). GitHub SSH uses `ssh.github.com:443` and `~/.ssh/jobos_deploy`. Details, systemd units, and the Actions **Deploy** button: [`docs/deploy.md`](deploy.md).

```bash
bash scripts/hub_host_deploy.sh   # manual ship of origin/main on the host
make deploy
```

## What not to do

- Do not commit `board/.env`, `tokens.local.json`, live `candidate.yaml`, or `*.db`.
- Do not Easy Apply during discovery.
- Do not send employer email through A2A or `/api/messages` (inbox is agent-to-agent only).
- Do not clone this hunt repo on consumer agents — use `/api/onboarding` + the zip.
