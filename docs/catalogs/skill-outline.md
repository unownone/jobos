# Skill outline

A **skill** is a reproducible playbook. GitHub files are the **starter** copy. The Hub **registry** (SQLite) is the live copy agents use, mutate, and submit for review.

If this document and a `SKILL.md` disagree, fix the skill.

## Why a registry

Hardcoded “sources / apply methods / outreach” do not scale. A Workday apply that works for one job must work for the next Workday job. A bot that mutates a playbook for one tenant must not leak that mutation to every other bot.

| Layer | Who writes | Who reads |
| --- | --- | --- |
| GitHub starters (`skills/*/SKILL.md`, `skills/starters/*.yaml`) | humans + maintainer in git | Hub seeder |
| Shared registry rows (`scope=shared`, `status=approved`) | **maintainer only** after proctor | every bot on that role |
| Local registry rows (`scope=local`) | the owning bot | **only** that bot |
| Maintainer queue (`skill.record`) | any track may **push** | **only** maintainer / admin **consume** |

Git is not deleted. Airgapped bots still load `skills/`. When `HUB_URL` is set, prefer `GET /api/registry/skills`.

## Attributes

```yaml
slug: apply-workday                 # stable id among shared skills
name: Workday apply
kind: skill                         # skill | mcp | http | builtin
role: apply                         # discovery | apply | outreach | research | maintain
tags: [apply, ats, workday]         # source | apply | outreach | research | maintain | …
platform: workday                   # platform catalog id or ATS name
match:
  ats: [workday]
  url_patterns: ["*.myworkdayjobs.com/*"]
  apply_kind: [ats]
reproducible: true                  # works for every job that matches, not one posting
inputs: [job, apply_packet, candidate]
outputs: [proof]
body: |                             # markdown playbook
  …
```

JSON Schema: [`ledger/schema/skill.schema.json`](../../ledger/schema/skill.schema.json).

### Role vs tag

- **role** is the permission lane (who may run it). Same names as process owners, plus `research` (shared capability) and `maintain`.
- **tags** classify the motion. Tagged skills are treated as:

| Tag | Meaning | Typical role |
| --- | --- | --- |
| `source` | Discover a kind of job on a platform | discovery |
| `apply` | Submit on an ATS or obscure site | apply |
| `outreach` | Email or LinkedIn DM | outreach |
| `research` | Company / people / posting check | any |
| `maintain` | Registry, lists, hunt board | maintain |

A discovery skill that sources Indeed is `role: discovery`, `tags: [source, board, indeed]`. An apply skill for an obscure Workday tenant is `role: apply`, `tags: [apply, ats, workday]`.

### Reproducibility bar

A skill is **reproducible** only if:

1. **Match, not a posting.** Select by `platform` / `ats` / `url_patterns` / `apply_kind`. Never “the Acme req from Tuesday.”
2. **Same steps, next job.** If Workday apply works for job A, job B on `*.myworkdayjobs.com` uses the same skill. Tenant-specific quirks stay on the bot’s **local** fork until the maintainer promotes a general version.
3. **Named I/O.** Inputs and outputs are the packet fields another bot already knows (`job`, `apply_packet`, `proof`).
4. **Expendable.** A better matching skill can replace this one. Local forks do not block shared updates.
5. **Workable.** Steps are boring and ordered. No “figure it out.” If a human is required (captcha, ID upload), the skill says `apply_blocked` / equivalent and stops.

Fail the bar → keep it local, or send it to the maintainer queue as a recording. Do not silently publish.

## Lifecycle

```
GitHub starter
    └─ Hub boot / pack rebuild seeds scope=shared status=approved origin=github

Worker uses shared skill
    ├─ follows it as-is
    └─ mutates for a tenant → scope=local origin=mutation (only that bot)

Anyone POST /api/registry/recordings  (or queue push skill.record)
    └─ only maintainer claims
          1. proctor (does it match, reproduce, stay in-role?)
          2. pass → promote to shared approved
             fail → declined; submitter may keep using the local copy
```

**Only maintainer consumes `skill.record` and decides.** Discovery / apply / outreach may enqueue. They must not ack another bot’s local skill into shared.

Statuses: `draft` → `recorded` → `proctoring` → `approved` | `rejected` | `retired`.

Scopes: `shared` (everyone on the role) | `local` (owning `user_id` only). Compat `X-Role` tokens own locals as `compat:{role}:{actor}`.

## Memory

A dedicated memory layer is **not in this pass**. Local skill forks are the only private, per-bot store. Do not invent a memories table.

## Hub API (live)

Auth: session, Bearer / `X-Hub-Key`, or compat role token. Unauthenticated → 401.

| Method | Path | Who |
| --- | --- | --- |
| GET | `/api/registry/skills` | any user: **shared approved** + **own local**. Query `tag`, `role`, `platform`, `ats`, `url`, `scope` |
| GET | `/api/registry/skills/{id}` | same visibility |
| POST | `/api/registry/skills` | create **local** draft / mutation |
| PATCH | `/api/registry/skills/{id}` | owner: local only. Maintainer/admin: shared |
| POST | `/api/registry/skills/{id}/fork` | copy shared (or own) → new local |
| POST | `/api/registry/recordings` | **any track** submits a recording; enqueues `skill.record` |
| GET | `/api/registry/recordings` | submitter: own. Maintainer/admin: all |
| POST | `/api/registry/recordings/{id}/proctor` | **maintainer/admin** after claim: `pass` \| `fail` |
| POST | `/api/registry/recordings/{id}/promote` | **maintainer/admin**, only after pass |
| POST | `/api/registry/seed` | maintainer/admin: re-seed GitHub starters (does not overwrite promoted non-github shared slugs) |

Queue kind `skill.record`: produce = every track; consume = **maintenance** and admin only.

## Git layout

| Path | What |
| --- | --- |
| `skills/<role-skill>/SKILL.md` | Cursor-loadable role playbooks (discovery, apply, outreach, …) |
| `skills/starters/<slug>.yaml` | Tagged platform playbooks seeded into the DB |
| `skills/lists/` | MCP/tool inventory (adopted / wanted / rejected) — not runnable skills |
| Hub `skills` table | Live registry after seed + proctor |

Role skills tell the bot to **select a matching tagged skill from the registry** when Hub is up, then fall back to the role playbook when airgapped.

## Maintainer proctor rubric

Pass only if all are true:

1. In-role (a `source` skill never Easy Applies).
2. Match block would select more than one real posting.
3. Steps are ordered, boring, and complete enough for another bot tomorrow.
4. No secrets, no other bot’s local text, no invented candidate facts.
5. Reproducible: swapping company/title/URL in the same ATS still works.

Then promote. Otherwise fail with a note; the local copy may remain.
