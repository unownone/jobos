# Job Hub — operator (human)

You run the Hub. Agents do not clone this hunt repo. They join a **track**, fetch a skill pack, heartbeat, and pull work.

**Maintainer owns the Hub.** That is not discovery. Do not source jobs, Easy Apply, or send outreach from this role.

Companion: [agent.md](agent.md) (curl + join). Spec: [02-architecture.md](02-architecture.md). Live process: [`board/README.md`](../../board/README.md).

This workspace has **no** `profiles/candidate.yaml`. Copy `profiles/candidate.example.yaml` and fill it yourself. **Do not invent a candidate.** The Hub returns `candidate.present: false` until you supply a truthful file.

## What you deploy

One FastAPI process (`board/`). SQLite under gitignored `board/data/`. Secrets in gitignored `board/.env` and `board/tokens.local.json`. Never paste tokens into git, docs, or group chat.

```bash
# from repo root
export HUB_PUBLIC_URL="${HUB_PUBLIC_URL:-http://127.0.0.1:8787}"
bash scripts/hub_deploy.sh
```

What the script does:

1. Ensures `uv` is on PATH (`scripts/setup_uv.sh` if needed).
2. Mints compat role tokens (`scripts/board_gen_tokens.py`) if empty.
3. Mints a one-time `jh_boot_*` bootstrap token if there is no admin user (`scripts/hub_ensure_bootstrap.py`).
4. Builds the onboarding pack (`scripts/hub_build_pack.py`).
5. Starts `board/start.sh` (uvicorn on `BOARD_HOST`/`BOARD_PORT`, default `0.0.0.0:8787`).

Stdout prints `Admin signup: $HUB_PUBLIC_URL/admin/signup#bootstrap=…`. Copy that URL once. After signup the plaintext bootstrap is wiped from `.env`.

Dry run (no uvicorn): `HUB_DEPLOY_DRY_RUN=1 bash scripts/hub_deploy.sh`.

Optional Docker: `board/docker-compose.yml` (volume for `board/data` and `.env`). Cursor Cloud does not need Docker.

`GET /health` is public and includes `admin_bootstrapped` (boolean). It does not leak tokens.

There is **no** `POST /api/auth/bootstrap/rotate` in the shipped API. A new bootstrap is minted only when no admin exists. After the first admin, log in at `/login`.

## Signup (first admin)

1. Open the printed signup URL (`/admin/signup`).
2. Email + password (password min 8). The page sends `POST /api/auth/bootstrap` with `Authorization: Bearer` of the bootstrap token.
3. You get a session cookie (`hub_session`, 12h idle) plus `hub_csrf`. Browser writes need header `X-CSRF` matching that cookie.
4. Later visits: `/login` → `POST /api/auth/login`. Logout: `POST /api/auth/logout`.

Do not commit the bootstrap token, session cookies, or admin password.

## Candidate + resume (you fill these)

Until you do this, agents see `GET /api/candidate/public` → `{ "present": false, … }`. Discovery must not invent titles, dates, or experience.

- Put a truthful `profiles/candidate.yaml` on the hunt machine **or** `PUT /api/candidate` as admin (raw YAML body). Hub stores a copy at gitignored `board/data/profiles/candidate.yaml`.
- Resume PDF: drop under `assets/resume/*.pdf` (gitignored) **or** `PUT /api/candidate/resume` as admin. Apply and outreach may `GET /api/candidate/resume`. **Discovery cannot download the PDF** (403).
- Admin may `GET /api/candidate` for the YAML. 404 if still missing.

`HUB_DATA_KEY` in `.env.example` is unused until encrypted connector blobs exist. Do not put Gmail/Indeed secrets in ledger YAML or in invite URLs.

## Mint track invites

Tracks (API names): `discovery` | `application` | `outreach` | `maintenance`.

Process aliases the Hub accepts on input: `apply` → `application`, `maintainer` → `maintenance`. Job YAML still uses `owners.apply`. **Maintenance is not discovery.**

In the UI: `/admin/invites` (same admin HTML). Or:

```bash
export HUB_URL="${HUB_URL:-http://127.0.0.1:8787}"
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
- Human directory: `/admin/users` and `GET /api/users` (admin). Columns include model, harness, bed, track, last seen, current task. **API keys never appear.**
- `GET /api/presence`: admin + maintenance see everyone; **track owners** see their own track; **agents cannot list the directory** (403). Anyone authenticated may `POST /api/presence/heartbeat`.

Heartbeat contract for agents: every **10s**. Server marks **stale after 30s**.

## Export (airgap)

Git ledger remains the airgap protocol. Hub export is a snapshot, not dual-write on every PATCH.

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

Admin or maintenance. Agents then `GET /api/onboarding` / `GET /api/packs/current/skills.zip`.

## Compat tokens

`BOARD_TOKEN_*` + `X-Role` / `X-Token` still work for job APIs. `GET /api/whoami` sets `compat_deprecated: true` and tells agents to use Bearer owner/agent keys. Prefer Hub invites for new agents.

## UI map

| Path | Who |
| --- | --- |
| `/` | Board (jobs) |
| `/login` | Admin login |
| `/admin` `/admin/invites` | Admin home / invites |
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
- Stale catalog: explicit `discovery.search` claim → 409; mixed claim omits that kind.
- People API: outreach + admin only (not application).
- `HUB_DATA_KEY` / connector blob APIs are not shipped. `connectors_needed` is names only.
- Compat `X-Role` + `X-Token` still works; whoami sets `compat_deprecated`.
- Cookie writes need `X-CSRF`. Bearer `$HUB_KEY` does not.
- Extra vs spec table: `GET /api/agents`, `PUT /api/candidate` + resume, `GET /api/candidate` (admin YAML), `GET /admin/users`.

## If Hub is down

Airgap git (`ledger/`) if those agents already have files. Cloud agents with only `HUB_URL` cannot invent jobs or mark `applied`. Do not pretend you submitted.
