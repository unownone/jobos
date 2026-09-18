# jobOS Hub (v1 spec)

This folder is the **design handoff** for turning the live hunt board into a **distributed jobOS Hub**: the only non-AI component. Agents (Grok, Claude, Cursor, others) register, authenticate, heartbeat, pull skills/scripts **without cloning this repo**, claim work from queues, and push/pull the board through the same APIs the UI uses.

**Status:** Hub is live on `board/` (auth, invites, onboarding, registry, memory, A2A). Operator/agent docs against **live routes**: [human.md](human.md), [agent.md](agent.md). Agents curl `/llms.txt` and `/agents.txt`.

**Do not treat the inventory table below as the live API.** It was the 2026-09-07 gap list. Auth is now Hub keys + sessions; registry and memory shipped. `profiles/candidate.yaml` is still not in git — Hub `/onboarding` is mandatory. Do not invent a candidate.

| Doc | What |
| --- | --- |
| [human.md](human.md) | Operator: deploy, **mandatory `/onboarding`**, invites, directory, export. |
| [agent.md](agent.md) | Agents: join, onboarding pack, heartbeat, queue, messages, A2A, role gates, `$HUB_KEY` curl. |
| [a2a.md](a2a.md) | A2A Agent Cards + JSON-RPC for agents outside this repo. |
| [memory.md](memory.md) | Worker / track / common memory pods (Hub Postgres, sparse writes, tenant-scoped). |
| [multi-tenant.md](multi-tenant.md) | Accounts, TenantContext, JobStore, Queue, BlobStore, session auth. |
| [install.md](../install.md) | Docker, Compose, `docker run`, uv, TLS, backups. |
| [deploy.md](../deploy.md) | Push to GitHub `main` deploys this host (Actions + watcher). |
| [demo](../demo/README.md) | Screenshots and video of the live Hub. |
| [01-grilling.md](01-grilling.md) | Ambiguity → **explicit decision** → one-line rationale. No TBD without a default. |
| [02-architecture.md](02-architecture.md) | Components, data model, queues, APIs, UI surfaces. |
| [03-pr-plan.md](03-pr-plan.md) | Independently mergeable phases A–H + implementer prompts. |

Shipped vs spec (document, do not “fix” here): no `POST /api/auth/bootstrap/rotate`; join HTML is `/join/{id}?s=`; people are outreach+admin only; agents cannot `GET /api/presence`; `apply.ready` is system-enqueue; catalog stale on `discovery.search` is 409 (or the kind is dropped from a mixed claim); `HUB_DATA_KEY` unused; compat `X-Role`/`X-Token` still works with `compat_deprecated` on whoami.

## What exists today (do not re-invent)

| Piece | Location | Gap vs Hub |
| --- | --- | --- |
| Process contract | `docs/process.md`, `docs/roles.md` | Roles; Hub is live |
| JobStore | Hub Postgres `jobs` / `events` | Tenant-scoped; git YAML is export-only |
| Hunt board | `board/` FastAPI + Postgres + RabbitMQ + BlobStore | Username/password session; compat `X-Role` is `acc_compat` |
| Token gen | `scripts/board_gen_tokens.py` | Compat only; signup does not need a dashboard token |
| Skills | Hub registry (`GET /api/registry/skills`) | Git `skills/` seeds the registry |
| Export | `GET /api/export/ledger` | Snapshot, not dual-write |

Grow **`board/`** into the Hub. Do not start a second Python service.

## Hard constraints (unchanged)

- Do not fabricate candidate experience.
- Do not apply during discovery (Easy Apply is apply-role).
- Default channels: email + LinkedIn DMs. No SMS.
- No credentials in committed hunt-board files (`board/.env`, `board/tokens.local.json`).
- Every state change still has an **event** + **job record**.
- Discovery starts with the catalog skill unless `docs/catalogs/skills-and-mcps.md` was updated this week.
- Maintainer is seldom-used and must not source jobs.

## Operator claim

This spec was written under **maintainer** (`ledger/INDEX.md` Active operators, 2026-09-07). Discovery/apply/outreach claims were not wiped.
