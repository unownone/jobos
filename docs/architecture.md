# Architecture

jobOS is a **job harness**: a multi-agent workflow whose live list is **jobOS Hub** (Postgres + BlobStore + RabbitMQ). The process is stateless. Git `ledger/` is an export snapshot, not canonical state.

## Goals

- One discovery lane that only finds and shortlists.
- One apply lane that only submits from a packet, with writing that is worth reading.
- One outreach lane that only emails and LinkedIn-DMs after a handoff.
- A shared live list on Hub (Postgres, tenant-scoped), plus an export tarball when you need files.
- Skills are **dynamic Hub registry records** (GitHub starters seed them), not hardcoded forever. Local mutations stay on the owning bot. Shared updates require maintainer proctor.
- MCP/tool inventory is discovered, vetted, listed in `skills/lists/`, and maintained.

## Components

```mermaid
flowchart LR
  subgraph inputs [Inputs]
    candidate[candidate.yaml]
    resumes[resume PDFs]
    catalog[skills and MCP catalog]
    starters[GitHub starters]
  end

  subgraph roles [Roles]
    d[Discovery]
    a[Apply]
    o[Outreach]
    m[Maintainer]
  end

  subgraph shared [Shared]
    research[Deep research]
    store[Hub JobStore]
    board[board/ live API + UI]
    registry[skill registry Postgres]
  end

  subgraph outputs [Outputs]
    packets[Apply packets]
    proof[Submit proof]
    touches[Email and LinkedIn touches]
  end

  candidate --> d
  resumes --> a
  resumes --> o
  catalog --> d
  catalog --> m
  starters --> registry
  registry --> d
  registry --> a
  registry --> o
  m --> catalog
  m --> board
  m -->|"proctor + promote"| registry
  research --> d
  research --> a
  research --> o
  d --> ledger
  d --> board
  ledger --> a
  board --> a
  a --> ledger
  a --> board
  ledger --> o
  board --> o
  o --> ledger
  o --> board
  d --> packets
  a --> proof
  o --> touches
```

### Candidate profile

Single file: `profiles/candidate.yaml`. Every role reads it. Nobody keeps a private fork of the target titles or deal-breakers unless they write the change back.

### Skill and MCP catalog

Not a vendor lock. Discovery searches public registries at the start of a cycle. The seldom-used **maintainer** writes the machine-readable lists in [`skills/lists/`](../skills/lists/) and keeps `docs/catalogs/skills-and-mcps.md` honest. See [`skill-and-mcp-catalog`](../skills/skill-and-mcp-catalog/SKILL.md) and [`skill-maintainer`](../skills/skill-maintainer/SKILL.md).

### Skill registry (Hub)

When `HUB_URL` is set, tagged playbooks live in SQLite (`skills` table), not as a second git source of truth. GitHub `skills/starters/` plus role `SKILL.md` seed `scope=shared` `origin=github` on boot / pack rebuild. Contract: [`docs/catalogs/skill-outline.md`](catalogs/skill-outline.md). Schema: [`ledger/schema/skill.schema.json`](../ledger/schema/skill.schema.json).

- **Shared** (`scope=shared`, `status=approved`): every bot on that role.
- **Local** (`scope=local`): the owning bot only. Worker mutations stay local.
- **Recordings** (`skill_recordings` + queue `skill.record`): any track may push; only maintainer / admin consume, proctor, then promote.

The catalog lists MCP/tools; the registry is the live skill body. Hub **memory pods** are the working set (`docs/job-hub/memory.md`). Track/common facts that should last become skills via `POST /api/memory/items/{id}/solidify` (`origin=memory`), then the same maintainer proctor/promote path. Private worker notes never solidify.

Airgapped bots still load `skills/`. Do not use another bot’s local skill.

### Deep research

A shared capability, not a fourth owner. Used to:

- Verify a posting is real and current
- Map the team and likely hiring manager
- Pull company language for apply copy
- Find emails and LinkedIn URLs for outreach

Preferred MCP: Exa. Local fallback the cloud agent can run: [dzhng/deep-research](https://github.com/dzhng/deep-research) via `scripts/run_deep_research.py` (Firecrawl + OpenAI). Other fallbacks: Firecrawl MCP, Tavily, Parallel Search MCP, built-in search. See [`docs/catalogs/deep-research.md`](catalogs/deep-research.md). Build plan: [`docs/research/platform-mcp-build-plan.md`](research/platform-mcp-build-plan.md).

The **maintainer** owner is for the skill tree, the Hub registry (proctor then promote), **and** the hunt board (schema, uptime), not for company research.

### JobStore (canonical)

Source of truth: Hub Postgres `jobs` / `events` / `people`, scoped by `account_id`. See [`job-hub/multi-tenant.md`](job-hub/multi-tenant.md). `GET /api/export/ledger` is a snapshot.

### Hunt board (live plane)

[`board/`](../board/README.md) is FastAPI + PostgreSQL + RabbitMQ + BlobStore. Username + password at `/login`. Compat `X-Role` + `X-Token` maps to `acc_compat` and is deprecated. **Maintainer owns it.** Discovery creates rows; apply and outreach only advance their fields; admin can stop or edit. Operator/agent docs: [`docs/job-hub/human.md`](job-hub/human.md), [`docs/job-hub/agent.md`](job-hub/agent.md).

**Memory pods** live in the same Hub Postgres: per-worker private, per-track shared, plus a common pod — all tenant-scoped. Agents recall every heartbeat and queue claim; writes are gated. Durable track/common facts may be **solidified** into the skill registry. [`docs/job-hub/memory.md`](job-hub/memory.md).

## Data flow for one job

```mermaid
sequenceDiagram
  participant D as Discovery
  participant L as Hub JobStore
  participant A as Apply
  participant O as Outreach
  participant R as Deep research

  D->>R: Company and posting check
  D->>L: POST /api/jobs (discovered)
  D->>L: Score, shortlist, write apply_packet
  A->>L: Claim apply_ready job
  A->>R: Language and recent news for copy
  A->>L: applied + proof + outreach_packet
  O->>L: Claim outreach_ready job
  O->>R: Hiring manager, teammates, execs
  O->>L: touches, waiting, chatting
```

## Packet design

Chat history is not a handoff. Packets are.

| Packet | Produced by | Consumed by | Must contain |
| --- | --- | --- | --- |
| `apply_packet` | Discovery | Apply | URL, ATS, account, steps, materials, known questions, why shortlisted |
| `outreach_packet` | Apply (seed) + Outreach (fill) | Outreach | Who to contact, why, resume file, one-line hook, do-not-contact |

Templates live in [`handoffs/`](../handoffs/).

## Subdivision

A role is a **permission set**, not a process count. Subdivisions are **tagged registry rows** when Hub is up (`GET /api/registry/skills?tag=…`). Airgap: role `SKILL.md` + `skills/starters/`.

```
Discovery
  ├─ source skills (tag=source): LinkedIn, Indeed, Wellfound, YC, RemoteOK, Hiring Cafe, Weekday, Google dorks
  ├─ marketplaces (Toptal, Lemon.io, Flexiple, Turing, BairesDev)
  └─ big-tech careers (Amazon, Microsoft, Google, Uber, ...)

Apply
  ├─ apply skills (tag=apply): greenhouse / lever / ashby
  ├─ workday / greenhouse-adjacent
  └─ linkedin easy apply (only after packet)

Outreach
  ├─ outreach skills (tag=outreach): email (PDF attached)
  └─ linkedin_dm (ask for a chat)

Maintainer (seldom, repo-wide)
  ├─ skills/lists + catalog + mcp.example.json
  ├─ Hub registry: seed starters, claim skill.record, proctor, promote
  └─ hunt board (board/): tokens, schema, uptime, hygiene, tunnels
```

Each subdivision still writes the same job file. If two discovery bots find the same posting, they merge onto one `id` (see sharing rules). Local mutations are `scope=local` on the same role, not a new owner.

## Runtime topologies

**One bot, all roles.** Allowed. Must still obey the order and the forbidden actions per phase.

**Three bots, three roles.** Default. Discovery owns Hub job creation.

**Many bots.** Split by portal or channel. Claim work on the Hub job (`owners.discovery`, `owners.apply`, `owners.outreach`) before mutating.

**Maintainer bot (rare).** Separate turn. Writes lists. Owns the hunt board. Claims `skill.record`, proctors, promotes. Does not search jobs. Worker mutations stay `scope=local` until then.

## What we deliberately do not build

- Auto Easy Apply from discovery
- SMS / WhatsApp
- Git as the live job list

The **Hub** in `board/` is maintainer-owned live infra. Secrets stay gitignored. Export YAML is a snapshot, not a second source of truth.
