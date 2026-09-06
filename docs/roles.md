# Roles

A role is a **permission set** plus a **skill**. People or bots pick one, several, or all. Combined ownership is allowed. Skipping the process order is not.

## The three owners

### Discovery owner

**Skill:** [`skills/job-discovery/SKILL.md`](../skills/job-discovery/SKILL.md)

**Also runs first:** catalog skill, deep research skill.

**Owns:** the ledger portal (conflict resolution, INDEX rebuild, schema), portal credentials that others may not have (Indeed OAuth, LinkedIn logged-in search, etc.).

**Writes:** new job files, scores, apply packets, `skipped` reasons.

**Must never:** submit an application, click Easy Apply, send outreach.

**May subdivide by portal.** Example claims:

- `discovery/indeed`
- `discovery/yc`
- `discovery/big-tech`
- `discovery/dorks`

Each subdivision still uses the same job schema. Dedup before create.

### Apply owner

**Skill:** [`skills/job-apply/SKILL.md`](../skills/job-apply/SKILL.md)

**Owns:** ATS logins used to submit, resume variants, the quality of the written materials.

**Writes:** `applying` / `applied` / `apply_blocked`, proof, seeded outreach packet.

**Must never:** invent a job, apply without a packet, start cold outreach.

**May subdivide by ATS or site:**

- `apply/greenhouse`
- `apply/workday`
- `apply/linkedin`

LinkedIn Easy Apply is an **apply** subdivision, not a discovery shortcut.

### Outreach owner

**Skill:** [`skills/job-outreach/SKILL.md`](../skills/job-outreach/SKILL.md)

**Owns:** Gmail (or other mail) drafts with PDF attachments, LinkedIn DMs, the people ledger.

**Writes:** touches, `waiting` / `chatting`, do-not-contact.

**Must never:** SMS, apply, attach nothing and call the email complete.

**May subdivide by channel:**

- `outreach/email`
- `outreach/linkedin`

## Combining roles

| Setup | How to run |
| --- | --- |
| Solo bot | Catalog → research → discover → stop. Then apply drip. Then outreach. Separate turns if needed so you do not Easy Apply mid-search. |
| Pair | Discovery + (apply and outreach together) |
| Trio | One owner each, default |
| Swarm | Subdivisions above, one INDEX |

When combined, keep the **forbidden column** in the README in your head. Combined is not “do everything at once.”

## Claiming work

Before mutating a job YAML:

```yaml
owners:
  discovery: "bot-or-human-name"
  apply: ""
  outreach: ""
```

If `owners.apply` is set by someone else and status is `applying`, do not steal it unless it is stale (no event for 24h) and you leave a note.

## Shared capabilities (not owners)

| Capability | Skill | Who uses it |
| --- | --- | --- |
| Skill/MCP discovery | `skill-and-mcp-catalog` | Discovery first; anyone when blocked |
| Deep research | `deep-research` | All three |

Do not create a fourth “research bot” unless the user asks. Research is a tool the owners call.

## Marketplace vs posting

Some “platforms” have no job board. The discovery owner still records them, with `apply_kind: network` or `outreach_only`. Apply may submit a network application. Outreach may be the whole motion. That is still three roles, one record.
