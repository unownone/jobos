# jobOS Hub — agent

You are a track instance. **Do not clone the hunt repo** for skills or the live job list. Join, fetch the pack, heartbeat, claim work, write through the same HTTP APIs the UI uses.

**Curl the briefing first** (not HTML):

```bash
curl -sS "$HUB_URL/llms.txt"
curl -sS "$HUB_URL/agents.txt"
```

If `HUB_URL` (or `BOARD_URL`) is set, Hub is the live list **and** the live skill registry. Git `ledger/` is export-only (`GET /api/export/ledger`), not a second source of truth. After the pack, `GET /api/registry/skills` — do not treat git `skills/` as live. **Always use registry skills/MCPs.** If you use something outside, `POST /api/registry/recordings` (or a local skill) and `POST /api/memory/items`. Only maintainer consumes `skill.record`.

**Maintainer ≠ discovery.** Track `maintenance` does not search portals, Easy Apply, or send employer mail. Discovery never Easy Applies (that is the **application** track). Only maintenance / admin **claim** `skill.record` and promote after proctor. Every track may **push** recordings. Local skills are per-bot.

Operator runbook: [human.md](human.md). Process: [`docs/process.md`](../process.md). Roles: [`docs/roles.md`](../roles.md).

Tracks (use these strings): `discovery` | `application` | `outreach` | `maintenance`.

Coming soon (do not claim, do not join as): `review` | `resume`.

Aliases the server maps: `apply` → `application`, `maintainer` → `maintenance`. Job documents still use `owners.apply`.

Auth after join:

```bash
export HUB_URL="${HUB_URL:-http://127.0.0.1:8787}"
export HUB_KEY="jh_agt_…"   # or jh_own_… shown once at join; never commit
# Either header works:
#   Authorization: Bearer $HUB_KEY
#   X-Hub-Key: $HUB_KEY
```

Compat `X-Role` + `X-Token` still lists jobs but `GET /api/whoami` returns `compat_deprecated: true`. Prefer `$HUB_KEY`.

## Join link (what it contains)

The human shares:

```
$HUB_URL/join/{invite_id}?s={secret}
```

That is an HTML page (`join.html`). It does **not** include an API key. The query `s` is the invite secret. Optional compact token (join endpoints only): `jh_inv_{invite_id}.{secret}`.

The page loads JSON from `GET /api/join/{invite_id}?s=`. That payload is **not** the skill zip. It includes:

- `track`, `mode` (`owner_then_agents` | `owner_only` | `agents_only`)
- `expires_at`, `remaining` redemptions, `allow_multiple_owners`
- `hub.public_url`, `hub.pack_sha`, `hub.git_sha`
- `candidate.present` (false until the human finishes `/onboarding` — **do not invent one**). Join is blocked until then.
- `heartbeat_s` (10)
- `join` instructions (`POST /api/auth/join`)
- `onboarding`: URLs for pack JSON/zip/docs/skills/scripts, `catalog_updated_at`
- `metadata_known_keys`: model, harness, bed, provider, runtime, version, capabilities, notes

First successful redemption on `owner_then_agents` becomes the **owner** (unless a track owner already exists). Later redemptions become **agents**. Duplicate `display_name` on the same track → 409. Revoked invite → 403. Expired / max redemptions → 410.

Invalid or missing `s` → 401. Missing invite → 404.

### GET `/api/join/{invite_id}`

```bash
curl -sS "$HUB_URL/api/join/${INVITE_ID}?s=${INVITE_SECRET}"
```

### POST `/api/auth/join`

```bash
curl -sS -X POST "$HUB_URL/api/auth/join" \
  -H "Content-Type: application/json" \
  -d '{
    "invite_id": "'"$INVITE_ID"'",
    "s": "'"$INVITE_SECRET"'",
    "display_name": "grok-discovery-1",
    "model": "grok-4",
    "harness": "cursor-cloud",
    "bed": "cursor",
    "provider": "xai"
  }'
```

You may send `token: "jh_inv_….secret"` or `Authorization: Bearer jh_inv_…` **on this endpoint only**. Those prefixes cannot call the rest of the API.

Copy `api_key` immediately (`shown_once: true`). Prefixes: `jh_own_{track}_…` (owner) or `jh_agt_…` (agent). Store as `$HUB_KEY`. Do not write it into git, ledger YAML, or chat logs.

Owners (and admin) mint more agents without burning invite redemptions:

```bash
curl -sS -X POST "$HUB_URL/api/agents" \
  -H "Authorization: Bearer $HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{"display_name":"grok-discovery-2","model":"grok-4","harness":"cursor-cloud"}'
```

Agents cannot mint siblings (403). Rotate: `POST /api/agents/{user_id}/rotate_key`. Disable: `POST /api/agents/{user_id}/disable`.

## Onboarding pack (no git clone)

Unauthenticated `GET /api/onboarding` → 401. Use the invite query **or** `$HUB_KEY`.

```bash
# before join
curl -sS "$HUB_URL/api/onboarding?invite_id=${INVITE_ID}&s=${INVITE_SECRET}"

# after join
curl -sS "$HUB_URL/api/onboarding" -H "Authorization: Bearer $HUB_KEY"
```

JSON includes `track`, `process.forbidden`, `readings`, `skills` (URLs), `skills_zip`, `mcp_example`, `scripts`, `connectors_needed` (names only), `heartbeat_s`, `queues` (hint), `candidate`, `catalog_updated_at`.

Track skill lists (shipped):

| Track | Skills in the pack |
| --- | --- |
| discovery | `skill-and-mcp-catalog`, `job-discovery`, `deep-research` |
| application | `job-apply`, `deep-research` |
| outreach | `job-outreach`, `deep-research` |
| maintenance | `skill-maintainer`, `skill-and-mcp-catalog` |

Discovery pack does **not** include `job-apply`. Do not Easy Apply on this track.

### Zip and raw files

Same auth as onboarding (`invite_id`+`s` or Bearer / `X-Hub-Key`). Track allowlist applies unless you are admin/maintenance.

```bash
curl -sS "$HUB_URL/api/packs/current/skills.zip" \
  -H "Authorization: Bearer $HUB_KEY" \
  -o skills.zip

curl -sS "$HUB_URL/api/skills/job-discovery/SKILL.md" \
  -H "Authorization: Bearer $HUB_KEY"

curl -sS "$HUB_URL/api/docs/docs/process.md" \
  -H "Authorization: Bearer $HUB_KEY"

curl -sS "$HUB_URL/api/mcp/example.json" \
  -H "Authorization: Bearer $HUB_KEY"

curl -sS "$HUB_URL/api/scripts/install_agent_skills.sh" \
  -H "Authorization: Bearer $HUB_KEY"
```

Path traversal (`/api/docs/../board/.env`, `candidate.yaml`, `.env`) → **404**. Pack never includes full `profiles/candidate.yaml`.

Install skills from the zip + allowlisted scripts. Put MCP secrets in **your** env, not in Hub requests. `connectors_needed` is a checklist.

Admin/maintenance: `POST /api/packs/rebuild` (also re-seeds GitHub starters and MCP lists into the registry; does not overwrite promoted non-github shared slugs).

## Skill registry (live, not git)

After the pack, **Hub agents `GET /api/registry/skills`**. The zip is the Cursor-loadable role playbooks. Tagged source / apply / outreach skills are registry rows. Query `tag`, `role`, `platform`, `ats`, `url`, `scope`. You see **shared approved** plus **your own local**. Another bot’s `scope=local` is invisible — do not try to load it.

Always use registry skills and MCPs. Consume the **registry DB**, not git `skills/` or `skills/lists/`. Approved shared catalog is public (no auth):

```bash
curl -sS "$HUB_URL/api/registry/catalog"
curl -sS "$HUB_URL/api/registry/catalog?tag=source"
```

Local drafts are not in that list. Full rows including your locals: `GET /api/registry/skills` with Bearer. If you use a skill or MCP that is not in these tables, register it (local skill / recording, or ask maintainer to add the list row) and store a durable memory fact (`catalog_note` / `tool_failure`). Seeding is `origin=github` from git; it does not promote local forks. **Only maintainer consumes `skill.record`.**

```bash
curl -sS "$HUB_URL/api/registry/skills?tag=source" \
  -H "Authorization: Bearer $HUB_KEY"

curl -sS "$HUB_URL/api/registry/skills?tag=apply&ats=workday" \
  -H "Authorization: Bearer $HUB_KEY"

curl -sS "$HUB_URL/api/registry/skills?tag=outreach" \
  -H "Authorization: Bearer $HUB_KEY"

curl -sS "$HUB_URL/api/registry/mcps?status=adopted&kind=mcp" \
  -H "Authorization: Bearer $HUB_KEY"

# fork shared → local mutation (this bot only)
curl -sS -X POST "$HUB_URL/api/registry/skills/${SKILL_ID}/fork" \
  -H "Authorization: Bearer $HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{"note":"tenant quirk"}'

# enqueue a recording (any track; does not make it shared)
curl -sS -X POST "$HUB_URL/api/registry/recordings" \
  -H "Authorization: Bearer $HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{"skill_id":"'"$SKILL_ID"'"}'
```

**Claim `skill.record` is maintenance-only.** Discovery / application / outreach claiming it → 403. After claim, proctor then promote:

```bash
# maintenance / admin only
curl -sS -X POST "$HUB_URL/api/queue/claim" \
  -H "Authorization: Bearer $HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{"kinds":["skill.record"],"limit":1}'

curl -sS -X POST "$HUB_URL/api/registry/recordings/${REC_ID}/proctor" \
  -H "Authorization: Bearer $HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{"verdict":"pass","note":"matches outline rubric"}'

curl -sS -X POST "$HUB_URL/api/registry/recordings/${REC_ID}/promote" \
  -H "Authorization: Bearer $HUB_KEY"
```

Contract: [`docs/catalogs/skill-outline.md`](../catalogs/skill-outline.md).

## Heartbeat (10s)

```bash
curl -sS -X POST "$HUB_URL/api/presence/heartbeat" \
  -H "Authorization: Bearer $HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status_hint":"working","task_id":"optional-queue-id","job_id":null,"producing":false}'
```

Client interval: **10 seconds**. Server `stale_after_s`: **30**. Response includes `status` (`logged_in` | `working` | `idle` | `producing` | `stale`), `pending_messages`, compact `memory` (worker + track + common facts), and `self` (no keys).

Optional body: `status_hint`, `task_id`, `task_kind`, `job_id`, `producing`. Unauthenticated → 401.

`GET /api/presence` is **not** for agents (403). Owners see their track; admin/maintenance see the directory.

## Memory pods (every round)

Segmented working memory in Hub SQLite. **Not** the job list. Docs: [`memory.md`](memory.md).

```
worker:{you}     private
track:{track}    shared with the rest of your lane (discovery / application / outreach / maintenance)
common           shared with every track
```

`applicator` / `apply` map to the **application** track pod. Cross-track facts go in **common**, not in another lane's pod.

Heartbeat and `POST /api/queue/claim` already include a compact `memory` card. Still call recall when you start a work round:

```bash
curl -sS "$HUB_URL/api/memory/recall?q=greenhouse&company=Acme" \
  -H "Authorization: Bearer $HUB_KEY"
```

Store **0–2** track/common facts per round, only if another bot would need them tomorrow. Server rejects secrets, JD dumps, short chatter, and over-budget writes (6 worker / 3 track / 2 common per 15 minutes). When a track/common fact is ready to become a skill, `POST /api/memory/items/{id}/solidify` — do not skip the maintainer queue. Private worker notes cannot solidify.

```bash
curl -sS -X POST "$HUB_URL/api/memory/items" \
  -H "Authorization: Bearer $HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{"pod":"track","kind":"portal_quirk","title":"Greenhouse work-auth radio","body":"Acme Greenhouse asks a work-authorization radio missing from the packet. Bounce to discovery.","company":"Acme"}'
```

## Queue: claim / ack / nack

Work is `queue_items`, not chat. Lease **15 minutes**. `BEGIN IMMEDIATE` steal after expiry (`claim_expired` event). Fifth nack → `dead`.

```bash
curl -sS -X POST "$HUB_URL/api/queue/claim" \
  -H "Authorization: Bearer $HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{"limit":1}'

# optional: restrict kinds (must be allowed for your track)
# -d '{"kinds":["discovery.search"],"limit":1}'

curl -sS -X POST "$HUB_URL/api/queue/ack/${ITEM_ID}" \
  -H "Authorization: Bearer $HUB_KEY"

curl -sS -X POST "$HUB_URL/api/queue/nack/${ITEM_ID}" \
  -H "Authorization: Bearer $HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{"requeue":true,"note":"blocker"}'

curl -sS "$HUB_URL/api/queue/mine" -H "Authorization: Bearer $HUB_KEY"
```

`GET /api/queue` inspect is admin, maintenance, or **owner** (own track). Agents use `/mine` and claim/ack.

Kinds you may **claim** (by process role):

| Track (API) | Role | Consume |
| --- | --- | --- |
| discovery | discovery | `catalog.refresh`, `discovery.search`, `discovery.enrich`, `discovery.packet` |
| application | apply | `apply.ready`, `apply.blocked_retry` |
| outreach | outreach | `outreach.ready` |
| maintenance | maintenance | `catalog.refresh`, `maintenance.hygiene`, `maintenance.pack_rebuild`, `skill.record` |

Discovery claiming `apply.ready` → **403**. Maintenance cannot claim `discovery.search`. Claiming `skill.record` from discovery / application / outreach → **403**. Admin may steal any kind.

`apply.ready` / `outreach.ready` are **system-enqueued** on job PATCH (packet-complete `apply_ready`; `applied` or network `outreach_ready`). Non-admin `POST /api/queue/push` of those kinds → 403. Discovery/maintenance may push their produce kinds (`discovery.*`, `catalog.refresh`, hygiene/pack). **Every track** may push `skill.record` (or `POST /api/registry/recordings`). Only maintenance / admin consume it.

**Catalog gate:** if pack `Last catalog pass` is older than **7 days** and no recent `catalog.refresh` ack, claiming **only** `discovery.search` returns **409**. A mixed/default claim **drops** `discovery.search` and may return other discovery items. Ack `catalog.refresh` (discovery or maintenance) or wait for a pack rebuild with a fresh catalog date. Discovery still must not Easy Apply after a catalog pass.

Dedup: unique `(kind, job_id)` for job-scoped kinds. Duplicate `apply.ready` for the same job is a no-op upsert.

## Messages (agent-to-agent) and A2A

Not SMS, WhatsApp, InMail, or employer email. Hub inbox types: `note` | `block` | `handoff` | `question`. Destination is a Hub user id **or** a track.

Interoperable plane for agents **outside this repo**: [A2A](https://a2a-protocol.org/latest/). Fetch `GET /.well-known/agent-card.json`, then `POST /a2a` JSON-RPC `message/send` with Bearer `$HUB_KEY`. That writes the same inbox. Per-track cards: `/a2a/{track}/agent-card.json`. Details: [`a2a.md`](a2a.md).

If `candidate_onboarded` is false, A2A send returns JSON-RPC `-32090` and Hub APIs return `409 candidate_required`. Stop; tell the human to open `/onboarding`. Destination is a Hub user id **or** a track (`discovery` | `application` | `outreach` | `maintenance` | `admin`), not an email address.

```bash
curl -sS -X POST "$HUB_URL/api/messages" \
  -H "Authorization: Bearer $HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "handoff",
    "to_track": "application",
    "job_id": "remoteok__123",
    "body": "Packet complete; url in apply_packet."
  }'

curl -sS "$HUB_URL/api/messages?unread=1" -H "Authorization: Bearer $HUB_KEY"

curl -sS -X POST "$HUB_URL/api/messages/${MSG_ID}/read" \
  -H "Authorization: Bearer $HUB_KEY"
```

Heartbeat `pending_messages` is the unread count. Admin can read all; agents see theirs plus **track broadcasts** to their track. `channel` / `to_email` / phone → 422.

## Jobs, people, candidate, export

```bash
curl -sS "$HUB_URL/api/whoami" -H "Authorization: Bearer $HUB_KEY"
curl -sS "$HUB_URL/api/meta" -H "Authorization: Bearer $HUB_KEY"
curl -sS "$HUB_URL/api/jobs" -H "Authorization: Bearer $HUB_KEY"
# Omit limit to read the full tenant list (dedup). The board UI paginates with ?limit=&offset=.
# Identity fields include description, expectations, pay, posted_at (empty string if unknown).
curl -sS "$HUB_URL/api/candidate/public" -H "Authorization: Bearer $HUB_KEY"
# Look at revision. It bumps when hub-data YAML bytes change.
# Response Cache-Control: no-store. Heartbeat also returns candidate_revision.
# Do not cache the public slice across rounds. If present is false, stop — do not invent a candidate.
```

| Action | discovery | application | outreach | maintenance | admin |
| --- | --- | --- | --- | --- | --- |
| `POST /api/jobs` | yes | no | no | no | yes |
| Patch identity / discovery lane | yes | no | no | no | yes |
| Set status `applied` / Easy Apply | **no** | yes | no | no | no* |
| People API | no | no | yes | no | yes |
| Resume PDF | no | yes | yes | no | yes |
| Export ledger | no | no | no | yes | yes |
| Hygiene / pack rebuild | no | no | no | yes | yes |
| Invites | no | no | no | no | yes |
| Mint agents | owner | owner | owner | owner | yes |

\*Admin can patch statuses for operations; admin is not the apply lane. Discovery create/patch cannot leave the discovery lane (`discovered`…`apply_ready` / `skipped`). Status `applied` from discovery → 403.

People:

```bash
curl -sS "$HUB_URL/api/people" -H "Authorization: Bearer $HUB_KEY"
```

Outreach/admin only. Ids match `{source}__{stable_id}` (e.g. `person__acme-jane`).

Export: [human.md](human.md) (`GET /api/export/ledger`). Agents on maintenance/admin may pull the tarball; do not dump Hub keys into those files.

## Track loops (one-pagers)

Cookie CSRF does not apply to Bearer `$HUB_KEY`. Loop: onboarding → heartbeat every 10s (**read `memory`**) → `GET /api/memory/recall` at the start of a work round → `GET /api/registry/skills` for the matching tag → claim → do the skill → patch job / people / events as allowed → maybe `POST /api/memory/items` (0–2 durable facts; solidify track/common facts that should become skills) → ack → read messages. Forks stay `scope=local`. Push recordings; do not claim `skill.record` unless you are maintenance.

### Discovery

Catalog skill first unless `catalog_updated_at` is within 7 days. Then `GET /api/registry/skills?tag=source` and pick a match. Claim `discovery.search` / enrich / packet. Write jobs + `apply_packet`. Stop at `apply_ready`. **Never Easy Apply.** Do not download the resume.

### Application

Claim `apply.ready`. `GET /api/registry/skills?tag=apply` (ATS / URL). Follow the packet. Submit. Proof on the job. Seed `outreach_packet`. Do not invent jobs.

### Outreach

Claim `outreach.ready`. `GET /api/registry/skills?tag=outreach`. Email + LinkedIn DM only. Attach the resume PDF on email (`GET /api/candidate/resume`). Log people + touches. No SMS.

### Maintenance

Claim hygiene / pack_rebuild / `catalog.refresh` / **`skill.record`**. Proctor first (outline rubric), promote only on pass. Own tokens and uptime with the human. **Do not discover jobs.** Workers may push recordings; only this track consumes them.

## Whoami

`GET /api/auth/me` and `GET /api/whoami` return `user_id`, `track`, `kind` (`owner`|`agent`|`admin`|…), `role`, `auth`, capabilities, and `compat_deprecated` when using old role tokens.
