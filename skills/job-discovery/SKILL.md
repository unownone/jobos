---
name: job-discovery
description: Discover and shortlist jobs for Job Apply OS. Covers LinkedIn, Indeed, Wellfound, Work at a Startup, Google Jobs and ATS dorks, RemoteOK, Hiring Cafe, Weekday, Roro Remote, talent networks (Flexiple, Turing, Toptal, Lemon.io, BairesDev), and big-company career sites. Writes apply packets. Never applies, including Easy Apply. Use when sourcing, searching, or shortlisting jobs.
role: discovery
tags: [source]
kind: skill
slug: job-discovery
reproducible: true
inputs: [candidate, platforms]
outputs: [job, apply_packet]
---

# Job discovery

You find work. You do not apply.

## Registry

When `HUB_URL` is set, **select a matching tagged `source` skill** from `GET /api/registry/skills?tag=source` (filter `platform`, `url`, or `ats`). GitHub starters seed that table. If you mutate a playbook for one portal, `POST /api/registry/skills/{id}/fork` and keep it **local**. Submit a recording for maintainer proctor if it should be shared. Airgapped: follow this role skill plus `docs/catalogs/platforms.md`.

Outline: `docs/catalogs/skill-outline.md`.

## Startup sequence

1. Read `AGENTS.md`, `profiles/candidate.yaml`, `docs/process.md` section 3.
2. If `docs/catalogs/skills-and-mcps.md` is stale, run `skills/skill-and-mcp-catalog/SKILL.md` first.
3. Load `docs/catalogs/platforms.md` and `docs/catalogs/big-tech-careers.md`.
4. Claim yourself via Hub presence / the invite for your track. Do not write git `ledger/INDEX.md` as live state.
5. If Hub is up, `GET /api/memory/recall` before the first search.

## Loop

For each platform in scope (user list, else the minimum viable set in process.md):

1. Search with the best available method (MCP, public API, public site, dorks).
2. Dedup against Hub `GET /api/jobs`.
3. `POST /api/jobs` from the example shape in `ledger/jobs/_example.yaml` (schema only).
4. Run `skills/deep-research/SKILL.md` on shortlist candidates.
5. Score 1–5. Veto deal-breakers.
6. If shortlisted, fill `apply_packet` using `handoffs/apply-packet.md` until another bot could apply tomorrow.
7. Set status `apply_ready` or `shortlisted` (if the user wants a manual gate) or `skipped` with a reason. If the company or the user already said no, set `status: rejected` with `rejection.by` (`company` | `user`) and remarks instead of leaving it open.
8. Hub appends the event. Do not append git `ledger/events.jsonl` as live state.
9. You consume the board; you do not issue tokens or change schema.

Stop at `max_shortlist_per_cycle`. Prefer a tight list.

## Memory (Hub)

If `HUB_URL` is set: recall `GET /api/memory/recall` at the start of the cycle (heartbeat already includes a compact card). Store **0–2** track/common facts at the end, only if another discovery worker would otherwise rediscover them (dead MCP, portal skip, search cursor). Worker notes are private. Never store JDs or secrets. [`docs/job-hub/memory.md`](../../docs/job-hub/memory.md).

## IDs

`{source}__{stable_id}` where `stable_id` is ATS req id or a slug of company + title + location. Example: `amazon__JOB-US-123`, `remoteok__123456`, `hiringcafe__abc123`.

## Hard no

- Easy Apply
- Form submit
- Messaging the poster
- Creating accounts “so you can apply”
- Inflating scores to fill the quota

If a listing is Easy Apply, record `apply_kind: linkedin_easy_apply` and leave it for the apply role.

## Network targets

Toptal, Lemon.io, Turing, Flexiple, BairesDev, and similar: one job file per network (or per open req if a real JD exists). `apply_kind: network` or `outreach_only`.

## Output to the user

A table of shortlisted ids, scores, and why. Point at INDEX.md. Do not paste every JD.
