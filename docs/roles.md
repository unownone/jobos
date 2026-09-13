# Roles

A role is a **permission set** plus a **skill**. People or bots pick one, several, or all. Combined ownership is allowed. Skipping the process order is not.

Job search has **three owners**. A fourth owner, **maintainer**, exists and is **seldom used**: it owns the skill/MCP tree, the Hub **skill registry** (seed + proctor queue), **and** the live hunt board, not job sourcing.

Discovery, apply, and outreach **consume** matching tagged skills from the registry when Hub is up. They do not promote shared skills.

## The three owners

### Discovery owner

**Skill:** [`skills/job-discovery/SKILL.md`](../skills/job-discovery/SKILL.md)

**Also runs first:** catalog skill, deep research skill. When Hub is up, pick a matching tagged skill (`GET /api/registry/skills?tag=source`).

**Owns:** the ledger portal (conflict resolution, INDEX rebuild, schema), portal credentials that others may not have (Indeed OAuth, LinkedIn logged-in search, etc.).

**Writes:** new job files, scores, apply packets, `skipped` reasons.

**Must never:** submit an application, click Easy Apply, send outreach. Must not consume `skill.record` or promote another bot’s local skill.

**May subdivide by portal.** Hub tags map claims to registry rows:

| Claim | Registry |
| --- | --- |
| `discovery/indeed` | `source-indeed` (`tags: [source, board, indeed]`) |
| `discovery/yc` | `source-yc` |
| `discovery/big-tech` | `source-big-tech` |
| `discovery/dorks` | `source-dorks` |

Each subdivision still uses the same job schema. Dedup before create. Local mutations of a source skill are `scope=local` on this role, not a fourth owner.

### Apply owner

**Skill:** [`skills/job-apply/SKILL.md`](../skills/job-apply/SKILL.md)

When Hub is up, pick a matching tagged skill (`GET /api/registry/skills?tag=apply`).

**Owns:** ATS logins used to submit, resume variants, the quality of the written materials.

**Writes:** `applying` / `applied` / `apply_blocked`, proof, seeded outreach packet.

**Must never:** invent a job, apply without a packet, start cold outreach. Must not consume `skill.record` or promote another bot’s local skill.

**May subdivide by ATS or site.** Hub tags:

| Claim | Registry |
| --- | --- |
| `apply/greenhouse` | `apply-greenhouse` (`tags: [apply, ats, greenhouse]`) |
| `apply/workday` | `apply-workday` |
| `apply/linkedin` | `apply-linkedin` |

LinkedIn Easy Apply is an **apply** subdivision, not a discovery shortcut. Local mutations are `scope=local` on this role.

### Outreach owner

**Skill:** [`skills/job-outreach/SKILL.md`](../skills/job-outreach/SKILL.md)

When Hub is up, pick a matching tagged skill (`GET /api/registry/skills?tag=outreach`).

**Owns:** Gmail (or other mail) drafts with PDF attachments, LinkedIn DMs, the people ledger.

**Writes:** touches, `waiting` / `chatting`, do-not-contact.

**Must never:** SMS, apply, attach nothing and call the email complete. Must not consume `skill.record` or promote another bot’s local skill.

**May subdivide by channel.** Hub tags:

| Claim | Registry |
| --- | --- |
| `outreach/email` | `outreach-email` (`tags: [outreach, email]`) |
| `outreach/linkedin` | `outreach-linkedin` |

Local mutations are `scope=local` on this role.

### Maintainer (seldom)

**Skill:** [`skills/skill-maintainer/SKILL.md`](../skills/skill-maintainer/SKILL.md)

**Also runs:** catalog skill as a subroutine (search registries, vet). Writes [`skills/lists/`](../skills/lists/). Consumes Hub `skill.record` and proctors against [`docs/catalogs/skill-outline.md`](catalogs/skill-outline.md).

**Owns:** `skills/` (in-repo SKILL.md files), `skills/starters/`, `skills/lists/`, `docs/catalogs/` inventory, `mcp/mcp.example.json`, cloud-agent tool wiring in `.cursor/environment.json`, the Hub **skill registry** (seed, claim `skill.record`, proctor, promote), and the **live hunt board** in [`board/`](../board/README.md) (tokens, schema, uptime, hygiene, share/tunnel setup).

**Writes:** adopted / wanted / rejected lists, catalog workspace log, example MCP config, environment install/egress. Rebuilds `skills/lists/INDEX.md`. Issues board role tokens out of band (never committed). Promotes recordings to `scope=shared` only after proctor pass.

**Must never:** discover jobs, Easy Apply, submit, send outreach, invent an MCP, put secrets in lists or in git, promote an un-proctored or another bot’s local skill without a pass.

**When to claim:** the user asks to maintain skills; the catalog is stale and nobody is mid-cycle; an MCP died; a research pass needs to be written into lists; the hunt board needs start/rotate/import; the registry has `skill.record` items to proctor. Not part of the daily discover → apply → outreach loop.

**Claim name:** `maintainer` (optionally `maintainer/lists`, `maintainer/board`, or `maintainer/registry`).

Discovery, apply, and outreach **consume** matching tagged skills and the board when it is running. They may **push** recordings. They do not own tokens, schema, uptime, or the proctor queue.

Local mutations are not a fourth owner. They are `scope=local` on the same role (owning bot only).

## Combining roles

| Setup | How to run |
| --- | --- |
| Solo bot | Catalog → research → discover → stop. Then apply drip. Then outreach. Separate turns if needed so you do not Easy Apply mid-search. |
| Pair | Discovery + (apply and outreach together) |
| Trio | One owner each, default |
| Swarm | Subdivisions above, one INDEX |
| Maintainer (rare) | Separate turn. Does not run inside a discovery search. |

When combined, keep the **forbidden column** in the README in your head. Combined is not “do everything at once.”

## Claiming work

Before mutating a job YAML:

```yaml
owners:
  discovery: "bot-or-human-name"
  apply: ""
  outreach: ""
  # maintainer is claimed on ledger/INDEX.md Active operators, not on a job YAML
```

If `owners.apply` is set by someone else and status is `applying`, do not steal it unless it is stale (no event for 24h) and you leave a note.

## Shared capabilities (not owners)

| Capability | Skill | Who uses it |
| --- | --- | --- |
| Skill/MCP discovery | `skill-and-mcp-catalog` | Discovery first; maintainer as a subroutine; anyone when blocked |
| Deep research | `deep-research` | All three job owners |

Do not create a fourth “research bot.” Research stays a tool the owners call. **Maintainer** is the fourth owner, and it is for the skill tree, the Hub registry, **and the hunt board**, not for company research. Worker-local skill forks stay on that role (`scope=local`).

## Marketplace vs posting

Some “platforms” have no job board. The discovery owner still records them, with `apply_kind: network` or `outreach_only`. Apply may submit a network application. Outreach may be the whole motion. That is still three roles, one record.
