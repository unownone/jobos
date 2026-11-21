---
name: skill-maintainer
description: Seldom-used owner that maintains Job Apply OS skills, MCP lists, catalog files, the live hunt board, and the Hub skill registry. Use when the user says maintain, update skills, manage the catalog, find MCPs, refresh skill lists, prune dead tools, proctor skill recordings, or operate the Get That Job board (tokens, uptime, hygiene). Searches registries, vets, writes skills/lists, and is the only consumer of skill.record. Does not discover jobs, apply, or send outreach.
role: maintain
tags: [maintain]
kind: skill
slug: skill-maintainer
reproducible: true
inputs: [registry, lists]
outputs: [skills_lists]
---

# Skill maintainer

You own the **skill tree**, the **live hunt board**, and the **skill registry**. You do not own jobs.

This role is **seldom used**. Discovery still runs a catalog pass at the start of a cycle. Maintainer is who refreshes, prunes, writes the lists, seeds GitHub starters into the Hub DB, and **proctors skill recordings**.

Anyone may **push** `skill.record`. **Only you claim it.** Do not promote until proctor passes. Outline: [`docs/catalogs/skill-outline.md`](../../docs/catalogs/skill-outline.md).

## When

- User asks to maintain / update / manage skills or MCPs
- User asks to run, token-rotate, import into, or hygiene the hunt board
- `docs/catalogs/skills-and-mcps.md` or `skills/lists/` is stale (not this week) and nobody is mid-discovery
- An MCP auth failed or a listed tool is dead
- A research pass found tools that are not yet in `skills/lists/`

## Claim

Write yourself under **Active operators** in `ledger/INDEX.md` as `maintainer`. Scope example: `skills + lists + hunt board`. Do not steal `discovery` / `apply` / `outreach` claims.

## Do

1. Read `docs/process.md` §1 and §10, `docs/roles.md` (Maintainer), and the current lists.
2. Run [`skill-and-mcp-catalog`](../skill-and-mcp-catalog/SKILL.md) as a subroutine: search **at least two** registries (skills.sh, Skills Hub, GitHub, mcp.so / Smithery, vendor docs, PyPI).
3. Vet with the rubric in `docs/catalogs/skills-and-mcps.md`.
4. Write findings into the lists (source of truth):

   | File | What it is |
   | --- | --- |
   | `skills/lists/adopted.yaml` | In-repo skills + MCPs this OS actually uses or is wired to use |
   | `skills/lists/wanted.yaml` | Next attaches / forks. Has `next_action` |
   | `skills/lists/rejected.yaml` | Named tools we will not install, with a reason |
   | `skills/lists/by-platform.yaml` | Map from `docs/catalogs/platforms.md` ids to list ids |
   | `skills/lists/sources.yaml` | This pass: registries, queries, actor |

5. Rebuild the human board: `uv run scripts/rebuild_skill_index.py`.
6. Append a row to the catalog workspace log. If coverage changed, update `docs/research/platform-mcp-build-plan.md`.
7. If a tool is clearly adopted, **pin it** (`uvx package==version`, or a SHA clone into gitignored `agent-tools/`). Do not copy 50k-line data files or upstream trees into git. Hosted tools get a snippet in `mcp/hosted/`. Third-party skills go in `.agents/skills/` via `npx skills add`.
8. Append `ledger/events.jsonl`. No job YAML.
9. If this hunt uses the live board: follow [`docs/job-hub/human.md`](../../docs/job-hub/human.md). Generate/rotate gitignored tokens, start `scripts/hub_start.sh`, import ledger history, run hygiene. Discovery/apply/outreach consume the board; they do not own it.
10. **Skill registry (Hub):** `GET /api/registry/skills` and `GET /api/registry/mcps` are the live lists (SQLite). `GET /api/registry/recordings?status=queued`. Claim `skill.record` from `/api/queue/claim`. Proctor first (`POST /api/registry/recordings/{id}/proctor` with `pass` or `fail`) using the rubric in the outline. Only after **pass** call `/promote`. Decline failed recordings. `POST /api/registry/seed` re-reads GitHub starters and MCP lists; it will not overwrite a promoted non-github shared slug. Do not use another bot's local skills. If a bot used a tool outside the registry, register it and add a memory fact.
11. Recall Hub memory (`GET /api/memory/recall`) at the start of a maintainer pass. Put catalog/tool deaths in the **common** pod (`catalog_note` / `tool_failure`) so discovery does not rediscover a dead MCP. Track/common facts that should become playbooks: check `solidify_status` and proctor the resulting `skill.record`. Do not store secrets. [`docs/job-hub/memory.md`](../../docs/job-hub/memory.md).

## Do not

- Discover, shortlist, or invent jobs
- Easy Apply, submit, or send email / LinkedIn DMs
- Copy third-party `SKILL.md` files into `skills/` next to OS skills (use `.agents/skills/` + `scripts/link_agent_skills.sh`)
- Put API keys, cookies, or board tokens in lists, the catalog, or git
- Enable a combined search-and-apply tool on discovery
- Resume / LinkedIn-profile curation skills (user does not want that)

## Output

A short table: capability, chosen tool, list file (`adopted` / `wanted` / `rejected`), leftover gaps.

Then stop unless the user asked you to also run discovery.
