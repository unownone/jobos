---
name: job-discovery
description: Discover and shortlist jobs for Job Apply OS. Covers LinkedIn, Indeed, Wellfound, Work at a Startup, Google Jobs and ATS dorks, RemoteOK, Hiring Cafe, Weekday, Roro Remote, talent networks (Flexiple, Turing, Toptal, Lemon.io, BairesDev), and big-company career sites. Writes apply packets. Never applies, including Easy Apply. Use when sourcing, searching, or shortlisting jobs.
---

# Job discovery

You find work. You do not apply.

## Startup sequence

1. Read `AGENTS.md`, `profiles/candidate.yaml`, `docs/process.md` section 3.
2. If `docs/catalogs/skills-and-mcps.md` is stale, run `skills/skill-and-mcp-catalog/SKILL.md` first.
3. Load `docs/catalogs/platforms.md` and `docs/catalogs/big-tech-careers.md`.
4. Claim yourself under **Active operators** in `ledger/INDEX.md`.

## Loop

For each platform in scope (user list, else the minimum viable set in process.md):

1. Search with the best available method (MCP, public API, public site, dorks).
2. Dedup against `ledger/jobs/`.
3. Create `ledger/jobs/<id>.yaml` from `ledger/jobs/_example.yaml`.
4. Run `skills/deep-research/SKILL.md` on shortlist candidates.
5. Score 1–5. Veto deal-breakers.
6. If shortlisted, fill `apply_packet` using `handoffs/apply-packet.md` until another bot could apply tomorrow.
7. Set status `apply_ready` or `shortlisted` (if the user wants a manual gate) or `skipped` with a reason.
8. Append `ledger/events.jsonl` and refresh INDEX.
9. If maintainer published `BOARD_URL` and your discovery token: POST the row to the hunt board as well (`board/README.md`). You consume the board; you do not issue tokens or change schema.

Stop at `max_shortlist_per_cycle`. Prefer a tight list.

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
