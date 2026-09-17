# Job Hub memory pods

Shared **working memory** for Job Apply OS agents. Not the job ledger. Not chat. Not embeddings-as-a-product.

Lives **inside Hub PostgreSQL**. Same Compose file. Postgres is not published on the host. No Hub volume, no extra vector-DB container, no paid API, no GPU.

## Why this, not Mem0 / Qdrant / Ollama

| Option | Why not for this machine |
| --- | --- |
| Mem0 / OpenMemory | LLM extraction stores too much (the opposite of “not aggressive”). Needs an embedder. |
| Qdrant + Ollama | Extra Compose services, RAM, and an embedding model for facts that are already short text. |
| Hosted memory SaaS | Not self-hosted. Secrets would leave the hunt host. |

Job Hub is already the only non-AI component. Agents already heartbeat every 10s and claim queue work. Recall piggybacks those calls. Retrieval is PostgreSQL `ILIKE` over short facts. That is the efficient fit.

## Pods

```
worker:{user_id}     private to that unique worker
track:{track}        shared by every worker on the track
common               shared by every track
```

Tracks: `discovery` | `application` | `outreach` | `maintenance`.

Aliases: `apply` / `applicator` → `application`; `maintainer` → `maintenance`. Compat `X-Role` workers get `worker:compat:{role}:{actor}` so two humans sharing a role token still have private pods if they set `X-Actor`.

| Pod | Who reads | Who writes | What belongs |
| --- | --- | --- | --- |
| Worker | that worker | that worker | Cursor, “page 4 next”, personal reminders. TTL 7 days. |
| Track | all workers on that track | that track | Portal quirks, blockers, search coverage, company notes. |
| Common | everyone | anyone (stricter kinds) | Dead tools, catalog notes, hub/process facts. |

Admin and maintenance may **inspect** other track pods (`GET /api/memory/items?pod=track:discovery`). They do not get other workers’ private notes on heartbeat.

Application (applicator) and outreach stay **separate** track pods. Cross-track facts go in **common**.

## Use every round

1. Heartbeat `POST /api/presence/heartbeat` includes a compact `memory` card (top facts, truncated).
2. Queue `POST /api/queue/claim` includes the same card, filtered by the claimed job when present.
3. At the start of a work round, also `GET /api/memory/recall?q=&company=&job_id=`.

Onboarding JSON advertises `memory.recall` / `memory.write`. Pack readings include this file.

```bash
curl -sS "$HUB_URL/api/memory/recall?q=greenhouse&company=Acme" \
  -H "Authorization: Bearer $HUB_KEY"
```

## Store sparingly

Do **not** log every thought. A write is for a fact another bot would otherwise rediscover tomorrow.

Allowed kinds:

| Pod | Kinds |
| --- | --- |
| Worker | `working_note`, `reminder`, `fact` |
| Track | `portal_quirk`, `blocker`, `tool_failure`, `company_note`, `process_note`, `person_hint`, `search_coverage` |
| Common | `process_note`, `tool_failure`, `catalog_note`, `candidate_constraint`, `hub_note` |

Gates (server-enforced):

- Title 8–120 chars. Body 40–800 (worker notes ≥24). Distill; no JD dumps.
- No secrets (`jh_agt_`, `BOARD_TOKEN`, `api_key`, passwords).
- No JSON/transcript blobs.
- Dedup on normalized hash (repeat write returns `status: exists`).
- Budget per worker per 15 minutes: **6** worker, **3** track, **2** common.
- Per round: **0–2** track/common writes. Skip if recall already has the fact.
- Worker notes expire in 7 days. Importance `1` track/common notes expire in 30 days. Importance `2–3` stay until forgotten.

```bash
curl -sS -X POST "$HUB_URL/api/memory/items" \
  -H "Authorization: Bearer $HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "pod": "track",
    "kind": "portal_quirk",
    "title": "Greenhouse work-auth radio",
    "body": "Acme Greenhouse asks a work-authorization radio missing from the packet. Bounce to discovery.",
    "company": "Acme",
    "importance": 2
  }'
```

Forget: `PATCH /api/memory/items/{id}` with `{"forget": true}` or `DELETE`.

Move or copy onto another pod (own track, `common`, or — for admin — any track). Incompatible kinds remap (`portal_quirk` → `process_note` on common). Pass `kind` to override.

```bash
curl -sS -X POST "$HUB_URL/api/memory/items/$MEM_ID/move" \
  -H "Authorization: Bearer $HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{"pod": "common", "copy": false}'
```

## Solidify into skills

Memory is the **working set**. Promoted registry skills are **long-term**. When a track or common fact is reusable tomorrow (portal quirk, dead tool, process note), snapshot it:

```bash
curl -sS -X POST "$HUB_URL/api/memory/items/$MEM_ID/solidify" \
  -H "Authorization: Bearer $HUB_KEY"
```

Rules:

- Only **track** and **common** facts. Private worker notes → 403.
- Author, maintainer, or admin. Other bots on the same track may **read** the fact; they cannot steal it.
- Creates a `skill_recordings` row with `origin=memory` and enqueues `skill.record`.
- Maintainer still proctors, then promotes. The shared skill keeps `origin=memory`.
- Repeat solidify of an open recording returns `status: exists`.

Do not skip the maintainer queue. Do not copy another bot’s local skill.

## API

| Method | Path | Who |
| --- | --- | --- |
| GET | `/api/memory/recall` | any authenticated worker |
| GET | `/api/memory/pods` | any |
| GET | `/api/memory/items?pod=` | own pods; inspectors may name another track/worker pod |
| POST | `/api/memory/items` | own worker / own track / common |
| PATCH/DELETE | `/api/memory/items/{id}` | author, or inspector for forget/delete |
| POST | `/api/memory/items/{id}/move` | author or inspector; `copy: true` leaves the original |
| POST | `/api/memory/items/{id}/solidify` | author or maintainer; track/common only |
| GET | `/admin/memory` | session (board UI) |

Candidate onboarding still gates these routes (`409 candidate_required`) like the rest of the Hub.

Memory is **not** exported in the git ledger tarball. It is live Hub state.

## UI

`/admin/memory` lists the pods the signed-in principal can see. Add, edit, delete, forget, or share/move a fact onto another writable pod. The board presence rail shows the compact heartbeat card.
