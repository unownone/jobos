# Job Hub grilling

Every ambiguity is enumerated, then **decided**. Rationale is one line. Defaults fit `docs/process.md` and the current `board/` overlay.

Track names in the Hub API: `discovery` | `application` | `outreach` | `maintenance`. Aliases: `application` = process role `apply`; `maintenance` = process role `maintainer`. `admin` is a **human hub owner**, not a job-search track.

---

## Product / identity

### Q1. Job Hub vs Job Board vs Job OS naming

**Decision**

| Surface | Name |
| --- | --- |
| Product / process / skills | **Job Apply OS** |
| Server (the only non-AI component) | **Job Hub** |
| Job list UI (today “Get That Job”) | **Board** (a Hub surface) |
| HTTP API prefix | `/api/...` on the Hub origin |
| CLI (v1) | `scripts/hub_*.py` / `board/start.sh`; binary name `jobhub` only if a later phase adds one |
| Browser title | `Job Hub — Board` (admin: `Job Hub — Admin`) |

**Rationale:** Keep OS as the contract agents already load; Hub is the new coordination plane; Board stays the list UI so we do not rename every screenshot and permission table at once.

### Q2. What stays git-ledger vs what moves to the Hub server

**Decision:** For a Hub-backed hunt, **SQLite on the Hub is canonical** for jobs, people, events, claims, messages, users, invites, and presence. Git `ledger/` remains the **airgap protocol and export format**: maintainer (or cron) may `GET /api/export/ledger` to write `jobs/*.yaml`, `people/*.yaml`, `events.jsonl`, rebuilt `INDEX.md`. Bots **without** a Hub keep using git only. Dual-write to git on every API mutation is **out of v1** (too slow; that is the bottleneck we are removing).

**Rationale:** The user asked for distributed management; git-as-queue is the stated bottleneck; process.md still requires an event + job record — those records live in the Hub DB with optional file export.

### Q3. Skills source of truth: git vs Hub snapshots

**Decision:** **Git remains the authoring source of truth** for `skills/`, `skills/lists/`, `mcp/mcp.example.json`, `docs/process.md`, and install scripts. The Hub **does not** let consumer agents push skill markdown. At deploy (and on maintainer `POST /api/packs/rebuild`), the Hub builds an immutable **pack** (`board/data/packs/<sha>/`) from the **server’s** checkout and serves it. Consumers never receive the hunt repo. If git and pack diverge, pack `git_sha` + `built_at` are visible on `/api/onboarding`; maintainer rebuilds.

**Rationale:** Skills are process, not hunt state; authoring in PRs stays reviewable; serving snapshots is how agents start without the repo.

---

## Auth

### Q4. Admin bootstrap token: generate, store, rotate

**Decision:** On first `board/start.sh` / `scripts/hub_deploy.sh`, if no admin user exists, generate `HUB_BOOTSTRAP_TOKEN` with `secrets.token_urlsafe(32)`, write it to gitignored `board/.env` and `board/tokens.local.json` under key `bootstrap` (plaintext only until consumed), print **once** to stdout: `Admin signup: http://<host>:<port>/admin/signup#bootstrap=<token>`. Persist **SHA-256** of the token in SQLite `secrets_meta`. First successful `POST /api/auth/bootstrap` creates the admin user, hashes the password (Argon2id), **deletes plaintext bootstrap from .env**, sets `bootstrap_used_at`. Rotation: admin `POST /api/auth/bootstrap/rotate` mints a new unused token (invalidates old unused); used bootstrap cannot mint a second admin unless `admin_count==0` (reinstall). Existing five `BOARD_TOKEN_*` role secrets remain valid in **compat mode** until phase B cuts over (see architecture).

**Rationale:** Matches today’s “generate on first start, gitignore, print”; one-time consume stops a leaked start log from remaining a standing admin credential.

### Q5. Admin creates invite tokens for bots to self-onboard

**Decision:** Admin UI **Invites** → create invite: `{track, max_redemptions (default 8), ttl_hours (default 72), mode: owner_then_agents | agents_only | owner_only}`. Stored hashed. Shareable URL: `{HUB_PUBLIC_URL}/join/{invite_id}?s={secret}` (secret in query because agents `curl` it; Hub never logs full URL). Admin can revoke. No invite in git or ledger YAML.

**Rationale:** Human remains the gate; agents can fetch a URL without a browser if they have curl.

### Q6. Bot registers as owner of a track

**Decision:** Tracks: `discovery` | `application` | `outreach` | `maintenance`. Default **one owner user per track**. Extra owners require admin checkbox `allow_multiple_owners`. First `owner_then_agents` redemption on an empty track creates the **owner**. Owner cannot register a different track with the same invite. Owner API key is shown **once**.

**Rationale:** Process already has one “owner” per role in INDEX; Hub makes that a real principal so they can mint workers.

### Q7. Owners create unique users (agent instances) under that track

**Decision:** `POST /api/agents` (owner or admin): creates user `{id, track, display_name, metadata, api_key}` unique per Hub. Agents cannot create sibling agents. Soft-delete + key revoke. Display names unique per track.

**Rationale:** Parallel Grok/Claude/Cursor workers need distinct identities for claims and presence; shared role tokens are the current collision source.

### Q8. Auth mechanism (practical, agents without a browser)

**Decision:** v1 mechanisms:

| Type | Format | Who | TTL | Scopes (coarse) |
| --- | --- | --- | --- | --- |
| `bootstrap` | `jh_boot_<urlsafe>` | first human | 7d or until used | `auth.bootstrap` |
| `invite` | `jh_inv_<id>.<secret>` | unauthenticated join | 72h default | `auth.join:<track>` |
| `session` | httpOnly `hub_session` cookie (random 32B, hashed in DB) | humans (admin, optional viewer) | 12h idle | UI + human APIs |
| `owner_key` | `jh_own_<track>_<urlsafe>` | track owner agent | none (rotatable) | track admin, mint agents, onboarding, queue push/pull for track, board lane, messages |
| `agent_key` | `jh_agt_<userId>_<urlsafe>` | agent instance | none (rotatable) | heartbeat, claim/ack own kinds, board lane for track, messages send/recv own inbox, read onboarding pack |
| `compat_role` (temporary) | existing `BOARD_TOKEN_*` + `X-Role` | old bots | until phase F | today’s board permissions; **no** claim leases; marked deprecated in `/api/whoami` |

Agents send `Authorization: Bearer <key>` **or** `X-Hub-Key`. Humans use cookie after signup. No OIDC in v1. JWTs: **not** in v1 (rotation and logout are simpler with opaque hashed keys). CSRF: SameSite=Lax cookies + `X-CSRF` for cookie-authenticated POST from the SPA.

**Rationale:** Opaque API keys are what curl/MCP/CLI agents already use; sessions are what a portal needs; JWT adds expiry complexity without helping self-host.

### Q9. Humans vs agents logging in

**Decision:** Humans: `/admin/signup` (bootstrap) then `/login` with email + password; session cookie; MFA out of v1. Optional `viewer` role (read board + presence, no invites) if admin invites a human with `track=null, kind=human`. Agents: **never** passwords; API keys only; they may open the Board UI by pasting the agent key into the existing Connect password field (Hub maps key → principal). Do not use Gmail as the Hub login in v1 (Gmail is an **extra connector**, Q10).

**Rationale:** Candidate/admin is a person on the portal; workers are programs; mixing OAuth-as-hub-login with outreach Gmail is a confusion hazard.

### Q10. Extra authentications `/onboarding` can request (no secrets in ledger)

**Decision:** Onboarding JSON includes `connectors_needed[]` with `{id, required, reason, auth_url, env_fallback}`. v1 catalog (static, maintainer-editable later):

| id | Typical track | How (v1) | Storage |
| --- | --- | --- | --- |
| `gmail` | outreach | Human completes Google OAuth **on the Hub** or agent sets `GMAIL_*` in **local** gitignored env and uses Cursor/Google MCP | Hub: encrypted blob in sqlite `connectors` or `board/tokens.local.json`; never YAML |
| `google_drive` | optional | Same | Same |
| `google_calendar` | outreach | Same | Same |
| `linkedin` | discovery list / outreach DM | **No password capture.** Status `human_session_required`. Agent uses its own browser profile; Hub only stores `linkedin_profile_url` of the **candidate** from `candidate.yaml` | No LinkedIn cookie in Hub v1 |
| `indeed` | discovery | OAuth if official MCP; else note | Encrypted if we ever proxy; v1 usually “agent’s MCP” |
| `exa` / `firecrawl` / `tavily` | research | Agent local env keys; Hub may store **encrypted** hunt-wide keys **only if admin pastes them in Admin → Secrets** | gitignored |

`GET /api/onboarding` returns **names and instructions**, never secret values. Agents write `blocked: connector:gmail` on tasks if missing.

**Rationale:** Process forbids credentials in the ledger; LinkedIn ToS makes cookie-vaulting a v1 non-goal.

---

## Onboarding links

### Q11. Shareable URL for a specified track

**Decision:** `{HUB_PUBLIC_URL}/join/{invite_id}?s={secret}`. Optional fragment unused (agents cannot always send fragments). Track is bound on the invite row, not spoofable in the query. `GET /join/...` (browser) shows a short HTML “you are joining **application**”. `GET /api/onboarding?invite_id=&s=` (or `Authorization` after join) returns the JSON pack. `POST /api/auth/join` with invite + metadata creates owner or agent and returns the API key **once**.

**Rationale:** One URL both a human can click and an agent can curl.

### Q12. Link contents, TTL, one-time vs reusable, how many agents

**Decision:** Default **reusable**, `max_redemptions=8`, `ttl_hours=72`, `mode=owner_then_agents` (1st = owner if none, rest = agents). Admin may set `max_redemptions=1` for a one-shot owner. After TTL or cap, 410. One track per link. Revoke is immediate. Audit event per redemption (`join`, actor, track, user id) **without** the secret.

**Rationale:** Swarm of 3 discovery Groks + 2 appliers fits default 8; TTL limits leaked chat pastes.

### Q13. `/onboarding` payload (enough without the repo)

**Decision:** JSON:

```json
{
  "hub": {"public_url": "", "version": "1", "git_sha": "", "pack_sha": ""},
  "track": "application",
  "process": {
    "must_read": ["process.md#apply-cycle", "roles.md#apply-owner"],
    "forbidden": ["invent jobs", "cold outreach", "skip packet"],
    "channels_default": ["email", "linkedin_dm"],
    "catalog_first": false
  },
  "readings": [{"path": "docs/process.md", "url": "/api/docs/docs/process.md", "sha256": ""}],
  "skills": [{"name": "job-apply", "files": ["/api/skills/job-apply/SKILL.md"]}],
  "skills_zip": "/api/packs/current/skills.zip",
  "mcp_example": "/api/mcp/example.json",
  "scripts": [{"name": "install_agent_skills.sh", "url": "/api/scripts/install_agent_skills.sh"}],
  "connectors_needed": [],
  "heartbeat_s": 10,
  "queues": ["apply.ready"],
  "candidate": {"present": false, "fields_public": ["target.titles", "target.locations"]}
}
```

Candidate **public slice** only (titles, locations, deal-breakers, work auth **label**, resume **download URL** if admin uploaded). No phone, no full bio dump to every discovery bot beyond what apply/outreach need. If `profiles/candidate.yaml` is missing on the server, `"present": false` and apply/outreach tasks stay blocked — **do not invent**.

**Rationale:** A cold agent with curl + zip can install skills and know the forbidden column.

### Q14. What “install skills” means without git

**Decision:** Hub serves (1) **zip of curated SKILL.md trees** for that track plus shared `deep-research` and `skill-and-mcp-catalog` as required, (2) **raw file API** `/api/skills/{name}/...` and `/api/docs/{path}`, (3) `mcp.example.json` plus `mcp/hosted/*.json`, (4) install scripts as text. Agent copies into its own `.cursor/skills` / `.claude/skills` / `.agents/skills`. Hub does **not** SSH into the agent. Third-party skills listed in `skills-lock.json` are referenced by `npx skills add ...` commands inside the pack `INSTALL.md`, not vendored unless already in the server checkout.

**Rationale:** Zip + raw files cover airgapped-ish agents; npx remains for marketplace skills the maintainer already pinned.

---

## Presence / heartbeats

### Q15. 10s heartbeat; appear when logged in AND heartbeating

**Decision:** `POST /api/presence/heartbeat` every **10s** with `{status_hint, task_id, producing}`. Presence row upsert. UI “logged in” requires a valid session/key **and** last heartbeat `< 30s` (`stale_after_s=30`). Cookie-only admin with no heartbeat shows as `logged_in` for 60s after any authenticated page load (UI pings the same endpoint). Agents that never heartbeat are **offline**, not listed as working.

**Rationale:** Matches the 10s ask; 3 missed beats = stale.

### Q16. Statuses

**Decision:** Exactly: `logged_in` | `working` | `producing` | `idle` | `stale`. Derivation (server, not client-trusted except `producing` hint):

| Status | Rule |
| --- | --- |
| `logged_in` | Auth valid; heartbeat fresh; no claim; not producing |
| `idle` | Alias of logged_in with no claim for `> 60s` (UI may badge idle) — **stored as `idle`** |
| `working` | Holds an unacked claim with valid lease |
| `producing` | `working` **and** (`producing=true` on last heartbeat **or** a job/event write in last 60s) |
| `stale` | Last heartbeat `> 30s`; leases expire independently |

`logged_in` vs `idle`: first 60s after connect = `logged_in`, then `idle` until a claim. Document both so the UI can match the user’s list.

**Rationale:** Maps to swarm ops (“who is actually writing”) without a fifth ad-hoc state.

### Q17. Admin directory

**Decision:** `GET /api/presence` (admin + maintenance): user id, display_name, track, kind (owner/agent/human), model, harness, bed, last_seen, status, current_task `{id, kind, job_id}`, ip hash optional **off by default**. No API keys in this payload.

**Rationale:** Maintainer already owns hygiene; this is live operator INDEX.

---

## Metadata on signup

### Q18. Agent metadata schema

**Decision:** Stored JSON `users.metadata` (schemaless extra allowed). v1 **known keys**:

```json
{
  "model": "grok-4",
  "harness": "cursor-cloud",
  "bed": "cursor",
  "provider": "xai",
  "runtime": "cloud-agent",
  "version": "2026-09-07",
  "capabilities": ["browser", "mcp", "email"],
  "notes": ""
}
```

`harness` = product driving the agent (cursor, claude-code, grok, openai-codex, custom). `bed` = where it sleeps (cursor, cli, browser, cron). Unknown keys stay in `extra` or sibling fields; Hub does not reject them. PATCH by the agent itself or owner.

**Rationale:** Extensible JSON; the three requested fields are first-class for the admin list.

---

## Queue / decoupling

### Q19. Each function + maintenance runs if a queue exists

**Decision:** Four **track inboxes** plus **messages** plus **maintenance**, all one table `queue_items` (SQLite v1). Discovery can run with zero apply agents (packets pile up as `apply.ready` jobs + queue items). Apply can run with zero discovery if items/jobs already exist. Outreach same. Maintenance hygiene/pack-rebuild never waits on discovery. Empty queue ⇒ agent heartbeats `idle`, does not invent jobs.

**Rationale:** This is the decoupling the user asked for; process order is enforced as **server-side kind gates**, not as “all roles must be online.”

### Q20. Queue design

**Decision:**

| Queue name (`kind` prefix) | Item | Produced by | Consumed by |
| --- | --- | --- | --- |
| `catalog.refresh` | “catalog stale or forced” | maintenance or discovery on cycle start if catalog `>7d` | discovery **or** maintenance (maintenance writes lists; discovery may only **read** pack) |
| `discovery.search` | `{portal, query}` | owner/admin or discovery fan-out | discovery agents |
| `discovery.enrich` | `{job_id}` | discovery after create | discovery |
| `discovery.packet` | `{job_id}` | discovery after score | discovery |
| `apply.ready` | `{job_id}` | **system** when status→`apply_ready` with complete packet | application |
| `apply.blocked_retry` | `{job_id}` | admin/human | application |
| `outreach.ready` | `{job_id}` | **system** when `applied` or `apply_kind` in `{network,outreach_only}` | outreach |
| `maintenance.hygiene` | `{}` | cron/admin | maintenance |
| `maintenance.pack_rebuild` | `{}` | admin/git hook | maintenance |
| `message` | `{to_user_id\|to_track, body, job_id?}` | any authenticated user | recipient(s) |

Jobs remain board rows; queue items are **work leases**. Dedup: unique `(kind, job_id)` for job-scoped kinds so three discovery bots do not enqueue three enrich jobs.

**Rationale:** Mirrors process lanes; system-enqueued apply/outreach prevents discovery from putting Easy Apply on the apply queue.

### Q21. Who may push/pull; locking / claim / ack

**Decision:**

- `POST /api/queue/claim` body `{kinds?: [], limit: 1}` — server filters to kinds allowed for principal.track. Uses `UPDATE ... WHERE status='open' AND (lease_until IS NULL OR lease_until < now) RETURNING` inside a SQLite immediate transaction. Sets `status=claimed`, `claimed_by=user_id`, `lease_until=now+15m`.
- Heartbeat with `task_id` extends lease by 15m.
- `POST /api/queue/ack/{id}` — success; for job-scoped items, job status must already be consistent or ack includes a job patch.
- `POST /api/queue/nack/{id}` `{requeue: true, note}` — open again; increment `attempts`; `attempts>=5` → `dead` + event.
- Stale lease: next claim steals; event `claim_expired`.
- Job row `owners.application` set to claiming agent on apply claim; 24h git stale rule **replaced** by lease (15m, extendable). Do not steal `applying` from a fresh lease.
- Discovery **cannot** claim `apply.*` or `outreach.*` (403). Application cannot `POST /api/jobs` (still). Maintenance cannot claim discovery.search.
- Three discovery agents: they claim **different** `discovery.search` portal tasks or different `job_id` enrich items; create-job still 409 on duplicate URL as today.

**Rationale:** Lease + ack is how parallel bots stop double-submitting; 15m fits a slow ATS form; heartbeat keeps long Playwright sessions.

### Q22. Inter-agent communication (not SMS)

**Decision:** Hub **inbox** only in v1 (`message` queue + `GET /api/messages`). Types: `note`, `block`, `handoff`, `question`. Optional `job_id`. Recipients: user, track, or `admin`. **Not** a substitute for email/LinkedIn to **employers**. Agents must not send candidate outreach through this channel. No WhatsApp/SMS/InMail. Email/LinkedIn remain Gmail MCP + LinkedIn DM per process. If an agent needs a human, message `admin` + set `apply_blocked`.

**Rationale:** Fits default channels; unblocks “packet incomplete” without git ping-pong.

---

## Board as integration surface

### Q23. Board UI as integration hub

**Decision:** One FastAPI app. Browser Board and agents call the **same** `/api/jobs`, `/api/events`, `/api/queue/*`, `/api/presence`. UI grows: presence rail, invites, onboarding copy button. No sidecar Node server.

**Rationale:** `board/` is already the live plane; splitting would duplicate permissions.

### Q24. Ledger semantics: keep git canonical or migrate

**Decision:** **Migrate live hunts to Hub DB** with **optional export** to `ledger/` (YAML + jsonl + INDEX). Schema of a job **stays** `ledger/schema/job.schema.json` (same statuses, packets, owners keys). Export uses existing filenames `ledger/jobs/<id>.yaml`. Import (`scripts/board_import_ledger.py`) stays for bootstrap. Git INDEX **Active operators** becomes a **projection** of Hub presence when export runs; until then humans may still edit INDEX for airgap hunts.

**Rationale:** Distributed agents cannot share git; file schema is the interchange and airgap story, not the lock server.

---

## Deploy

### Q25. Simple deploy then admin signup then invites

**Decision:** `scripts/hub_deploy.sh` (phase A): (1) ensure uv, (2) generate bootstrap if needed, (3) `board/start.sh`, (4) print signup URL. Human opens admin panel, sets email/password, lands on Invites. Admin creates four track invites, pastes URLs to agents. Docker Compose (`board/docker-compose.yml`) is **supported** for self-host (hub service, volume for `board/data` and `.env`) but **not required**. Cursor Cloud: no Docker assumption; `start.sh` + `0.0.0.0:8787` as today; `HUB_PUBLIC_URL` may be a tunnel the maintainer sets. Do not put tokens in tunnel URLs.

**Rationale:** First start already generates tokens; we add bootstrap + “open the panel” instead of a new platform.

### Q26. Secrets stay gitignored

**Decision:** Continue `board/.env`, `board/tokens.local.json`, `board/data/*`. Add `board/data/hub.sqlite` (may replace `board.db` in place by adding tables). Encrypted connector blobs in SQLite, key `HUB_DATA_KEY` in `.env`. Never ledger, never `docs/`.

**Rationale:** AGENTS.md already names those files.

### Q27. Cursor Cloud constraints

**Decision:** Hub is optional in Cloud agents that only have git; if `BOARD_URL`/`HUB_URL` is set, they **must** use Hub APIs and **must not** Easy Apply in discovery. Cloud egress + MCP stay on the **agent** side. Pack rebuild uses the workspace checkout the Hub process can read (`/workspace` on the hunt machine). If Hub is not running, airgap git protocol remains valid — but this spec’s implementers build the Hub, they do not delete git.

**Rationale:** Cloud agents already hit `board/` on a shared host; compose may be unavailable.

---

## Process constraints (locked)

| Topic | Decision |
| --- | --- |
| Fabricated experience | Server does not generate cover letters; agents still bound by profile |
| Apply during discovery | 403 on apply kinds + create-job cannot set `applied` |
| Channels | Onboarding `channels_default` email + linkedin_dm; no SMS kinds |
| Credentials in ledger | Export strips `connectors` and tokens |
| Events | `events` table append-only; export jsonl |
| Catalog first | If pack `catalog.updated_at` older than 7 days, discovery claim of `discovery.search` is refused until `catalog.refresh` acked (maintenance **or** discovery catalog skill). Catalog was updated 2026-09-06 at spec time — within the week, so a Hub built that week may skip force-refresh. |
| Maintainer vs discovery | Separate tracks; maintenance queue cannot include portal search kinds |

---

## Inventory facts that drove defaults

- Board auth is **one token per role**, `X-Actor` is free-text and unused for isolation (`board/app/auth.py`).
- No claim table; `owners.*` is advisory; git used 24h stale steal.
- No heartbeat; admin UI is Connect-with-role-token (`board/app/static/index.html`).
- Jobs+events SQLite already match ledger schema (`board/app/db.py`).
- `profiles/candidate.yaml` is **absent** in this workspace; Hub must advertise `candidate.present=false` until the human fills it.

---

## Non-goals (v1)

See [03-pr-plan.md](03-pr-plan.md#non-goals-v1). Defaults if someone asks anyway: **no**.
