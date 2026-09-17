# Install and host jobOS Hub

jobOS Hub is the live coordination plane for the job harness. One FastAPI process. SQLite on a volume. Agents do **not** clone this repo. They curl `$HUB_URL/llms.txt` and `$HUB_URL/agents.txt`.

**Onboarding is the first thing you do after the process is up.** Until a truthful candidate profile exists, jobs, invites, queues, messages, and A2A sends return `409 candidate_required`. Do not copy `profiles/candidate.example.yaml` into production.

Full operator API: [`docs/job-hub/human.md`](job-hub/human.md). Agents: [`docs/job-hub/agent.md`](job-hub/agent.md). A2A: [`docs/job-hub/a2a.md`](job-hub/a2a.md).

## Pick an install

| How | When | Command |
| --- | --- | --- |
| **Docker Compose (plain)** | Laptop, single VM, port 8787 | `docker compose up -d --build` or `docker compose -f docker-compose.plain.yml up -d --build` |
| **Docker Compose + Traefik** | Public host, ports 80/443 | `HUB_PUBLIC_HOST=your.host bash scripts/hub_docker.sh` (file: `docker-compose.traefik.yml`) |
| **`docker build` / `docker run`** | One container, no Compose | See [Docker (no Compose)](#docker-no-compose) |
| **uv / bare metal** | Cursor Cloud, no Docker | `bash scripts/hub_deploy.sh` |
| **Push to `main`** | This OCI host (Traefik + Hub already up) | [Deploy on push](deploy.md) |

Docker Desktop, Engine 24+, or Compose v2 is enough. Traefik is **optional**. This GitHub repo deploys to the hunt machine on every push to `main` — see [`docs/deploy.md`](deploy.md). Feature screenshots: [`docs/demo/README.md`](demo/README.md).

## First-run sequence (every install)

1. Start the Hub (one of the commands above).
2. Open the printed **Admin signup** URL (`/admin/signup#bootstrap=jh_boot_…`). Create the only human admin. The bootstrap token is wiped.
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

## Docker Compose (plain)

Hub only. Binds **8787**. Persistence is the `hub-data` volume (`/data` in the container: sqlite including **memory pods**, packs, candidate yaml, resume, `.env`). There is no separate vector database.

```bash
cd /path/to/jobos
export HUB_PUBLIC_HOST=127.0.0.1:8787   # or your VM IP:8787
docker compose up -d --build
# equivalent named project:
docker compose -f docker-compose.plain.yml up -d --build
docker compose -f docker-compose.plain.yml logs -f hub
```

Equivalent wrapper: `bash scripts/hub_docker_plain.sh`.

Open `http://127.0.0.1:8787/admin/signup`. After signup, `/onboarding`.

Override the published port with `HUB_PORT=343` if 8787 is taken (`http://127.0.0.1:343` — also set `HUB_PUBLIC_HOST` / `HUB_PUBLIC_URL` to match).

Stop: `docker compose -f docker-compose.plain.yml down` (keeps the volume). Destroy data: `down -v`.

## Docker Compose + Traefik (public host)

Ports **80** and **443** plus **8787**. The board is at `/`. File-based Traefik config (no Docker socket): `traefik/traefik.yml`, `traefik/dynamic.yml`.

```bash
# hostname, IPv4, or IP:port. :443 → https:// on invite URLs.
HUB_PUBLIC_HOST=hunt.example.com bash scripts/hub_docker.sh
# uses docker-compose.traefik.yml
# or
HUB_PUBLIC_HOST=12.234.244.34 docker compose -f docker-compose.traefik.yml up -d --build
```

Put a real TLS certificate in front if you need one (Traefik `websecure` already terminates TLS with a default cert; replace with Let’s Encrypt or a load-balancer cert in production). Do not put tokens in the public origin.

## Coolify

Coolify has no universal one-click URL. Create a **Docker Compose** resource pointed at this GitHub repo.

1. Source: `https://github.com/unownone/jobos` (branch `main`).
2. Compose file: `docker-compose.yml` (Hub on 8787, volume `hub-data`). Do not invent a second stack.
3. Set `HUB_PUBLIC_URL` (and usually `HUB_PUBLIC_HOST`) to the Coolify FQDN, e.g. `https://hub.example.com`.
4. Persist the named volume. Onboarding YAML and sqlite live under `/data`.
5. After first boot, open `/admin/signup` then `/onboarding`. Healthcheck is `GET /health` on 8787 inside the container.

Same image as Railway and local Compose (`Dockerfile` at repo root).

## Railway

Use the README **Deploy on Railway** button (`railway.json` + `Dockerfile`). Railway injects `PORT`; the entrypoint copies it to `BOARD_PORT` so uvicorn binds the port the platform probes.

Set after the first domain exists:

```bash
HUB_PUBLIC_URL=https://<your-railway-domain>
HUB_PUBLIC_HOST=<your-railway-domain>
JOBOS_NONINTERACTIVE=1
```

Mount a volume at `/data` (sqlite, candidate yaml, resume, secrets). Healthcheck path is `/health`. Do not require `ready_for_agents` for the probe — that stays false until onboarding.

## Docker (no Compose)

```bash
docker build -t jobos-hub .
docker run -d --name jobos-hub --restart unless-stopped \
  -p 8787:8787 \
  -e JOBOS_NONINTERACTIVE=1 \
  -e HUB_PUBLIC_HOST=127.0.0.1:8787 \
  -e HUB_PUBLIC_URL=http://127.0.0.1:8787 \
  -v jobos-data:/data \
  jobos-hub

docker logs -f jobos-hub   # copy the Admin signup URL
```

Same image as Compose. Same `/data` layout. Same onboarding gate.

## Bare metal (uv)

Needs Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
bash scripts/setup_uv.sh          # if uv is missing
export HUB_PUBLIC_HOST=127.0.0.1:8787
bash scripts/hub_deploy.sh
```

Listens on `0.0.0.0:8787`. Secrets: gitignored `board/.env` and `board/tokens.local.json`. SQLite: `board/data/board.db`. Dry run: `HUB_DEPLOY_DRY_RUN=1 bash scripts/hub_deploy.sh`.

## Reverse proxy / TLS

Plain Compose already publishes 8787. For a hostname:

- **Caddy** (example): `hunt.example.com { reverse_proxy 127.0.0.1:8787 }`
- **nginx**: `proxy_pass http://127.0.0.1:8787;` plus WebSocket-unrelated HTTP/1.1
- **Cloudflare Tunnel / Tailscale**: point at 8787; set `HUB_PUBLIC_URL` to the public origin so invite links work
- **Traefik template**: repo-root `docker-compose.yml`

Always set `HUB_PUBLIC_URL` (or `HUB_PUBLIC_HOST`) to the origin browsers and agents actually use. Never put `jh_boot_` / `jh_agt_` / `BOARD_TOKEN_*` in that URL.

## Persistence and backups

| Path in container | What |
| --- | --- |
| `/data/board.db` | Jobs, users, queue, messages, A2A tasks/peers |
| `/data/packs/` | Skill/MCP zip snapshots |
| `/data/profiles/candidate.yaml` | Live candidate (not git) |
| `/data/candidate-resume.pdf` | Resume PDF |
| `/data/hub.env` + `tokens.local.json` | Role + bootstrap secrets |

Backup the Docker volume (`docker volume inspect jobos-plain_hub-data` or `jobos_hub-data`). Airgap export for git: admin `GET /api/export/ledger`.

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
| Lost admin password | Restore `/data` from backup. Do not invent `candidate.yaml` to “unblock”. |
| Docker healthcheck failing | `docker compose logs hub`. `/health` must answer on 8787 inside the container. |
| Traefik 404 | Confirm `traefik/dynamic.yml` service URL is `http://hub:8787` and the `hub` service is healthy. |

## Deploy on push (this host)

GitHub `unownone/jobos` is origin. A push to `main` rebuilds Job Hub on the OCI box (`/home/opc/jobos-live`, Docker Compose + Traefik, volume preserved). Pull requests run **Deploy check** first (SSH wiring; no ship). GitHub SSH uses `ssh.github.com:443` and `~/.ssh/jobos_deploy`. Details, systemd units, and the Actions **Deploy** button: [`docs/deploy.md`](deploy.md).

```bash
bash scripts/hub_host_deploy.sh   # manual ship of origin/main on the host
make deploy
```

## What not to do

- Do not commit `board/.env`, `tokens.local.json`, live `candidate.yaml`, or `*.db`.
- Do not Easy Apply during discovery.
- Do not send employer email through A2A or `/api/messages` (inbox is agent-to-agent only).
- Do not clone this hunt repo on consumer agents — use `/api/onboarding` + the zip.
