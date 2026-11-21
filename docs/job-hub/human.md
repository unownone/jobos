# jobOS Hub — operator (human)

You run the Hub. Agents do not clone this hunt repo. They join a **track**, fetch a skill pack, heartbeat, and pull work. Share the join URL plus: curl `$HUB_URL/llms.txt` and `$HUB_URL/agents.txt` (not a browser).

**Always use registry skills/MCPs.** Tell agents: if they use something outside, they must register it and add a memory fact. You (maintainer) still own `skill.record` proctor.

**Maintainer owns the Hub.** That is not discovery. Do not source jobs, Easy Apply, or send outreach from this role.

Hub seeds GitHub `skills/` + `skills/starters/` into the **skill** registry and `skills/lists/` + `mcp/mcp.example.json` into the **MCP** registry on boot, first start, migrate, and pack rebuild. Agents use `GET /api/registry/skills` and `GET /api/registry/mcps`, not git. Admin/maintainer UI: `/admin/skills`. Do not paste API keys into skill bodies or recordings. Candidate `/onboarding` is still mandatory first.

Companion: [agent.md](agent.md) (curl + join). Spec: [02-architecture.md](02-architecture.md). Live process: [`board/README.md`](../../board/README.md).

This workspace has **no** live `profiles/candidate.yaml` until you finish Hub **`/onboarding`**. Copying the example file as if it were real is rejected. **Do not invent a candidate.** Until `GET /health` shows `candidate_onboarded: true`, invites, jobs, queues, messages, and A2A sends return `409 candidate_required`.

Install and hosting: **[`docs/install.md`](../install.md)** (Docker, Compose plain/Traefik, `docker run`, uv, TLS, backups). A2A: [`a2a.md`](a2a.md).

## What you deploy

The live Hub is the Go API plus the React SPA ([`docs/runtime.md`](../runtime.md)). PostgreSQL holds durable tenant state when `DATABASE_URL` is set. Queue leases are rows in `queue_items`. RabbitMQ is not part of this runtime. Files go through the blob driver (memory, filesystem, or S3). Secrets stay in gitignored env files. Never paste tokens into git, docs, or group chat.

Auth is **username + password** at `/login` (signup on the same page). No dashboard token is required. Multi-tenant design: [`multi-tenant.md`](multi-tenant.md).

```bash
# from repo root
export HUB_PUBLIC_HOST="${HUB_PUBLIC_HOST:-127.0.0.1}"   # hostname, IP, or IP:port
bash scripts/hub_deploy.sh
```

Or Docker:

```bash
docker compose up -d --build
# SPA http://127.0.0.1:8080  API http://127.0.0.1:8081
```

Full hosting: [`docs/install.md`](../install.md). **After signup, open `/onboarding` before minting invites.**

`HUB_PUBLIC_HOST=12.234.244.34:343` becomes `http://12.234.244.34:343` on invite URLs. `:443` becomes `https://`. A full `HUB_PUBLIC_URL` still wins.

`scripts/hub_deploy.sh` starts the Go API and serves the React SPA on `BOARD_HOST`/`BOARD_PORT` (default `0.0.0.0:8787`). Compose runs those as two containers.

What the script does:

1. Mints compat role tokens into gitignored `board/.env` and `board/tokens.local.json` when they are empty.
2. Mints a one-time `jh_boot_*` bootstrap token and prints the signup URL.
3. Builds `web/dist` when it is missing, then starts `go run ./cmd/hub`. The API reads the skill tree from the repo, so there is no separate pack step.

Stdout prints `Admin signup: $public_origin/admin/signup#bootstrap=…` once for a **fresh** deploy. After that, anyone may create an account at `/login` (username + password). `/admin/signup` still consumes the one-time bootstrap token if no admin exists yet.

Dry run (does not start the API): `HUB_DEPLOY_DRY_RUN=1 bash scripts/hub_deploy.sh`.

`GET /health` is public and includes `admin_bootstrapped` (boolean). It does not leak tokens.

There is **no** `POST /api/auth/bootstrap/rotate` in the shipped API. A new bootstrap is minted only when no admin exists. After the first admin, log in at `/login`.

## Signup

1. Open `/login` (or the printed `/admin/signup` URL on a brand-new Hub).
2. Username + password (password min 8). `POST /api/auth/signup` — no dashboard token.
3. You get a session cookie (`hub_session`, 12h idle) plus `hub_csrf`. Browser writes need header `X-CSRF` matching that cookie.
4. The UI then **requires** [`/onboarding`](#candidate--resume-mandatory-first) **for that account**.
5. Later visits: `/login` → `POST /api/auth/login`. Logout: `POST /api/auth/logout`.

Do not commit session cookies or passwords. Compat `X-Role` + `X-Token` still exists for tests; prefer session or Bearer keys.

## Candidate + resume (mandatory first)

This is the first operator action after admin signup. The Hub does not proceed without it.

- UI: `/onboarding` (identity, titles, locations, proof, resume PDF).
- Or `PUT /api/candidate` as admin (JSON or YAML). Stored in Postgres `hub_blobs` (survives Hub container rebuilds).
- Resume: `PUT /api/candidate/resume` or a PDF under `assets/resume/`. Apply and outreach may `GET /api/candidate/resume`. **Discovery cannot download the PDF** (403).
- `GET /api/candidate/status` and `/health` expose `candidate_onboarded` / `ready_for_agents` without dumping PII.
- Admin may `GET /api/candidate` for the YAML. 404 if still missing.
- The example identity `Ada Example` / `ada@example.com` is rejected.

`HUB_DATA_KEY` in `.env.example` is unused until encrypted connector blobs exist. Do not put Gmail/Indeed secrets in ledger YAML or in invite URLs.

## Mint track invites

Tracks (API names): `discovery` | `application` | `outreach` | `maintenance`.

Process aliases the Hub accepts on input: `apply` → `application`, `maintainer` → `maintenance`. Job YAML still uses `owners.apply`. **Maintenance is not discovery.**

In the UI: `/admin/invites` (same admin HTML). Or:

```bash
export HUB_URL="${HUB_URL:-http://127.0.0.1:8080}"
# Cookie session from the browser is easier. From curl, use an admin Bearer after you have one,
# or stay on the Invites page so you never put the key in a committed file.

curl -sS -X POST "$HUB_URL/api/invites" \
  -H "Authorization: Bearer $HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "track": "discovery",
    "mode": "owner_then_agents",
    "max_redemptions": 8,
    "ttl_hours": 72,
    "allow_multiple_owners": false
  }'
```

Create one invite per track you actually staff. Response (secret **once**):

- `join_url` — `$HUB_PUBLIC_URL/join/{invite_id}?s={secret}` (share this)
- `token` — `jh_inv_{id}.{secret}` (optional; agents can POST that as Bearer on join only)
- `secret` — query `s=`

`GET /api/invites` lists invites **without** secrets. `POST /api/invites/{id}/revoke` → later joins 403.

Modes: `owner_then_agents` (default; first redemption is the track owner, later ones are agents), `owner_only`, `agents_only`. Expired or exhausted invites → 410.

Paste join URLs to agents out of band. Do not put `s=` in git.

## Directory and presence

- Board UI: `/` (Connect with a key, or admin cookie). Presence rail uses `GET /api/presence` when allowed.
- Human directory: `/admin/users` and `GET /api/users` (admin). Columns include model, harness, bed, track, last active, current task. **API keys never appear.**
- `GET /api/presence`: admin + maintenance see everyone; **track owners** see their own track; **agents cannot list the directory** (403). Anyone authenticated may `POST /api/presence/heartbeat`.

Heartbeat: **any authenticated Hub action** refreshes presence. Agents may still `POST /api/presence/heartbeat` (optional). Server marks **stale after 5 minutes**. Directory shows **Last active** as a relative time. Each explicit heartbeat (and each queue claim) includes a compact **memory** card: that worker's private pod, the track's shared pod, and common. Inspector UI: `/admin/memory`. Protocol: [`memory.md`](memory.md). Do not treat memory as a second job list.

## Export (airgap)

`GET /api/export/ledger` writes a snapshot tarball (`ledger/INDEX.md`, `events.jsonl`, `jobs/*.yaml`, `people/*.yaml`). Secrets are stripped. Hub DB remains canonical; this is not dual-write.

```bash
curl -sS "$HUB_URL/api/export/ledger" \
  -H "Authorization: Bearer $HUB_KEY" \
  -o ledger-export.tar.gz

# or JSON (jobs + people + events, no BOARD_TOKEN / connector blobs)
curl -sS "$HUB_URL/api/export/ledger?format=json" \
  -H "Authorization: Bearer $HUB_KEY"
```

Admin or **maintenance** only. Tarball contains `ledger/INDEX.md`, `ledger/events.jsonl`, `ledger/jobs/*.yaml`, `ledger/people/*.yaml`. Secrets are stripped; export refuses if `BOARD_TOKEN` or `blob_encrypted` residue is detected.

Import the other way: `uv run scripts/board_import_ledger.py` (admin/maintenance `POST /api/import`).

## People (outreach)

Hiring contacts live on the Hub (`GET/POST/PATCH /api/people`). Outreach + admin only. Do not store tokens/passwords in people records. Export writes `ledger/people/`.

## Connectors (names only)

Onboarding JSON lists `connectors_needed` (Gmail, Exa, Indeed, …) with **ids and reasons, never secret values**. Agents attach MCP credentials in **their** environment. You do not paste OAuth into the Hub in v1.

## Pack rebuild

After you edit skills/docs on the hunt machine:

```bash
curl -sS -X POST "$HUB_URL/api/packs/rebuild" \
  -H "Authorization: Bearer $HUB_KEY"
```

Admin or maintenance. Agents then `GET /api/onboarding` / `GET /api/packs/current/skills.zip`. Rebuild also re-seeds GitHub starters into the registry (does not overwrite promoted non-github shared slugs).

## Skill registry

GitHub OS skills and `skills/starters/` are defaults written into SQLite (`skills` table). MCP/tool inventory from `skills/lists/` and `mcp/mcp.example.json` lands in the `mcps` table. Agents use `GET /api/registry/skills` and `GET /api/registry/mcps`, not git, as the live list. Contract: [`docs/catalogs/skill-outline.md`](../catalogs/skill-outline.md).

UI: `/admin/skills` (admin + maintenance). Proctor `skill.record` there or via API. Promote only on pass. Do not paste API keys. Local skills stay per-bot; do not copy another bot’s local body into shared. Track/common memory facts become recordings via `/admin/memory` **Solidify** or `POST /api/memory/items/{id}/solidify`.

Candidate `/onboarding` is still mandatory first. Registry seed does not invent a candidate.

## Compat tokens

`BOARD_TOKEN_*` + `X-Role` / `X-Token` still work for job APIs. `GET /api/whoami` sets `compat_deprecated: true` and tells agents to use Bearer owner/agent keys. Prefer Hub invites for new agents.

## UI map

| Path | Who |
| --- | --- |
| `/` | Board (jobs) |
| `/login` | Admin login |
| `/admin` `/admin/invites` | Admin home / invites |
| `/admin/skills` | Admin / maintenance: registry + proctor |
| `/admin/memory` | Session: memory pods; solidify track/common facts |
| `/admin/signup` | First admin |
| `/admin/users` | Directory |
| `/join/{invite_id}?s=` | Agent join page |
| `/health` `/ready` | Public |

## Shipped vs spec (do not “fix” in docs)

Documented from live `board/` routes on the Hub API branch:

- No `POST /api/auth/bootstrap/rotate`. Bootstrap is first-admin only, then wiped.
- Join URL is `/join/{id}?s=` plus `GET /api/join/{id}?s=`. Invite compact token `jh_inv_{id}.{secret}` works on join only.
- `GET /api/presence` is admin/maintenance/owners — **not agents**. Heartbeat is any authenticated user.
- `apply.ready` / `outreach.ready` are system-enqueued; agents cannot push those kinds.
- `skill.record`: any track may push; only maintenance/admin claim, proctor, and promote.
- Stale catalog: explicit `discovery.search` claim → 409; mixed claim omits that kind.
- People API: outreach + admin only (not application).
- `HUB_DATA_KEY` / connector blob APIs are not shipped. `connectors_needed` is names only.
- Compat `X-Role` + `X-Token` still works; whoami sets `compat_deprecated`.
- Cookie writes need `X-CSRF`. Bearer `$HUB_KEY` does not.
- Extra vs spec table: `GET /api/agents`, `PUT /api/candidate` + resume, `GET /api/candidate` (admin YAML), `GET /admin/users`.

## If Hub is down

Airgap git (`ledger/`) if those agents already have files. Cloud agents with only `HUB_URL` cannot invent jobs or mark `applied`. Do not pretend you submitted.
