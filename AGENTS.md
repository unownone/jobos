# Agent operating rules

You are working in **jobOS**, a job harness — the only harness you need to find a job. It can be distributed among multiple agents for an efficient loop and better recon.

If Hub is up, start with curl (not a browser):

```bash
curl -sS "$HUB_URL/llms.txt"
curl -sS "$HUB_URL/agents.txt"
```

Always use registry skills/MCPs (`GET /api/registry/skills` after join). If you use something outside the registry, record it and add a memory fact. Maintainer owns `skill.record`.

## Preferred path

If you are connected to jobOS MCP (`/mcp`), you are one agent. You are not stuck in a single lane.

1. Call `get_started`.
2. Ask the human which of find, apply, and outreach this session should run. Store the answer with `set_session_lanes`. Do not pick the lanes yourself.
3. `report_capabilities` with the truth. Find and apply need a browser. Outreach needs email. `evaluate_lane` before that work.
4. `start_loop`, then keep calling `next_loop` until it is done or blocked.
5. Read `skills/agent-session/SKILL.md`.

The human observes and steers at `/connect`. The older invite-key lanes below still work when you joined that way. Prefer MCP when both are available. Contract: `docs/job-hub/agent-flow.md`.

## Identity

1. Read `profiles/candidate.yaml` **or** Hub `GET /api/candidate/public`. If it is missing / `present: false`, stop for the human to finish `/onboarding`. Copy `profiles/candidate.example.yaml` only as a template. Do not invent a candidate.
2. Read `docs/process.md` if you have not already this session.
3. Claim a role from `docs/roles.md`. Write the claim on Hub presence / invites, not git `ledger/INDEX.md`.
4. If Hub is live, `GET /api/memory/recall` (or read `memory` on the first heartbeat) before searching or claiming work.

If the user says you own everything, you still run the three roles **in order**: catalog + research + discovery, then apply, then outreach. Never Easy Apply during discovery. Maintainer is a fourth owner and is **seldom** used; run it when the skill/MCP inventory, the Hub registry, or the proctor queue is the work, not mid-search.

## Role picker

| If the user says | Load |
| --- | --- |
| discover, source, shortlist, find jobs | `skills/job-discovery/SKILL.md` |
| apply, submit, cover letter, easy apply | `skills/job-apply/SKILL.md` |
| outreach, email, LinkedIn DM, referral, hiring manager | `skills/job-outreach/SKILL.md` |
| find skills, find MCPs, skillhub, skills.sh | `skills/skill-and-mcp-catalog/SKILL.md` |
| research the company, find the hiring manager, deep research | `skills/deep-research/SKILL.md` |
| maintain, update skills, manage catalog, skill lists, hunt board, skill registry, proctor | `skills/skill-maintainer/SKILL.md` |
| review / resume | Coming soon. Do not load a skill. Do not claim. |

Discovery **starts** with the catalog skill unless `docs/catalogs/skills-and-mcps.md` was updated this week. When Hub is up, also `GET /api/registry/skills?tag=source` and pick a matching tagged **source** skill. Apply uses `?tag=apply` (ATS / site). Outreach uses `?tag=outreach` (channel). Airgap falls back to the role `SKILL.md` plus `skills/starters/`.

If the work is **updating the skill tree itself** (lists, mcp.example.json, pruning dead tools), **operating the hunt board**, or **the skill registry + proctor queue** (`skill.record`), that is the seldom-used **maintainer** role, not discovery. Maintainer owns the registry and consumes `skill.record`.

**Coming soon (stubs only, do not claim):** `review` (feedback on profile/resume and shortlisted jobs) and `resume` (ATS-friendly tailoring). They are not owners and are not Hub invite tracks.

## Hard rules

- Do not fabricate experience, employers, dates, or metrics.
- Do not apply during discovery. Easy Apply counts as applying.
- Do not send SMS, WhatsApp, or InMail sequences unless the user explicitly adds that channel later. Default channels are **email** and **LinkedIn DMs**.
- Do not dump credentials into the ledger or the hunt board repo files. Put secrets in gitignored files (`board/.env`, `board/tokens.local.json`).
- Do not scrape authenticated pages you do not have an account for.
- Prefer official APIs, public JSON feeds, and public career pages.
- Attach PDFs on **email**. LinkedIn DMs usually cannot take a PDF; send a short note and ask for a chat, and point at a resume link if you have one.
- Every state change gets a Hub event (`POST`/`PATCH` jobs) and a row on the tenant job. Git `ledger/` is export-only.
- Any patch role (discovery, apply, outreach, admin) may set `status: rejected` with `rejection.by` (`company` | `user`) and remarks. Do not invent a reason.
- Local skills are **per-bot**. Do not load, copy, or promote another bot’s `scope=local` skill.
- Only maintainer consumes `skill.record` and promotes after proctor. Discovery / apply / outreach may enqueue recordings; they must not ack them into shared.
- If Hub is up (`HUB_URL` / `BOARD_URL`): **recall memory every round** (`GET /api/memory/recall` and the `memory` card on heartbeat / queue claim). Store only durable facts (portal quirks, blockers, dead tools). Do not dump transcripts, JDs, or secrets. Pods: worker (private) / track (shared on the lane) / common. Track/common facts that should become playbooks: `POST /api/memory/items/{id}/solidify`. Docs: [`docs/job-hub/memory.md`](docs/job-hub/memory.md).

## Ledger writes

Canonical record: Hub DB (`GET /api/jobs`). Git `ledger/jobs/<id>.yaml` is export-only.

- Create a new job through Hub APIs when discovering.
- Update in place for status, packets, and notes.
- Events append in Postgres (`/api/events`).
- `GET /api/export/ledger` writes a snapshot when you need git/airgap.

If two bots touched the same file, keep both packets, do not delete the other role’s fields, and leave a `conflicts` note.

## Voice

Applications and outreach should be specific, short, and worth reading. No “passionate synergistic self-starter.” Proof over adjectives. Match the company’s language only when it is already in the posting or in sourced research.

## When blocked

Write `apply_blocked` or a `blocked` note with the exact missing thing (login, work auth question, missing PDF, captcha, portal down). Do not pretend you submitted.

## Job Hub (if `HUB_URL` or `BOARD_URL` is set)

Use the Hub as the **live** job list (heartbeat, queue claim/ack, board APIs) and the **live skill registry** (`GET /api/registry/skills`). Do not treat git `ledger/` as a second live board for that run. Do not clone the hunt repo for skills — fetch `/api/onboarding` and the pack zip, then select tagged skills from the registry. Operator: [`docs/job-hub/human.md`](docs/job-hub/human.md). Agent: [`docs/job-hub/agent.md`](docs/job-hub/agent.md). **Maintainer ≠ discovery.** Maintainer consumes `skill.record` and promotes after proctor. Never Easy Apply on the discovery track. If `profiles/candidate.yaml` is missing, stop for the human; do not invent a candidate.
