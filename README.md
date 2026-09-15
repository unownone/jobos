# Job Apply OS

[![CI](https://github.com/unownone/jobos/actions/workflows/ci.yml/badge.svg)](https://github.com/unownone/jobos/actions/workflows/ci.yml)
[![Deploy check](https://github.com/unownone/jobos/actions/workflows/deploy-check.yml/badge.svg)](https://github.com/unownone/jobos/actions/workflows/deploy-check.yml)
[![Deploy](https://github.com/unownone/jobos/actions/workflows/deploy.yml/badge.svg)](https://github.com/unownone/jobos/actions/workflows/deploy.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

[![Open in Cursor](https://img.shields.io/badge/Open%20in-Cursor-000000?style=for-the-badge)](https://cursor.com/en/download)
[![GitHub](https://img.shields.io/badge/GitHub-unownone%2Fjobos-181717?style=for-the-badge&logo=github)](https://github.com/unownone/jobos)
[![Install Hub](https://img.shields.io/badge/Install-Hub-2ea44f?style=for-the-badge)](docs/install.md)
[![Feature demo](https://img.shields.io/badge/Feature-demo-6f42c1?style=for-the-badge)](docs/demo/README.md)
[![Deploy on push](https://img.shields.io/badge/Deploy-on%20push%20to%20main-1f883d?style=for-the-badge)](docs/deploy.md)

A template for a **distributed job search**, not a single auto-apply bot.

One repo. Three exclusive job-search roles, plus a seldom-used maintainer. One shared ledger. Bots can be airgapped.

```
Discovery finds and shortlists.
Apply submits with writing worth reading.
Outreach follows up by email and LinkedIn only.
Maintainer (seldom) updates skills and MCP lists.
Nobody jumps the queue.
```

This is the agent-facing operating system: how to pick a role, which skills and MCPs to attach, how to share work without hosting a server, and how to hand off a job so another bot can finish it.

For a live multi-agent hunt on a shared machine, maintainer also runs the private **Get That Job** board (`board/`): FastAPI + SQLite + admin UI (Job Hub). That board is the live coordination plane. The git ledger remains the template and airgap protocol. See [`board/README.md`](board/README.md), [`docs/job-hub/human.md`](docs/job-hub/human.md), [`docs/job-hub/agent.md`](docs/job-hub/agent.md).

## Start here

**Onboard the candidate before anything else.** The Hub will not let you hunt, invite agents, or send A2A messages until a truthful profile exists. Do not invent one. Do not ship `candidate.example.yaml` as live data.

1. **Install the Hub** — [`docs/install.md`](docs/install.md) / [`INSTALL.md`](INSTALL.md).
   - Plain Docker Compose: `docker compose -f docker-compose.plain.yml up -d --build`
   - Traefik (80/443): `HUB_PUBLIC_HOST=your.host bash scripts/hub_docker.sh`
   - `docker run` and uv/bare metal are in the same guide.
   - **This host:** push to `main` deploys automatically — [`docs/deploy.md`](docs/deploy.md). Feature walkthrough: [`docs/demo/README.md`](docs/demo/README.md).
2. **Create the admin** at the printed `/admin/signup` URL (one-time).
3. **Fill `/onboarding`** (identity, titles, locations, resume PDF). This is mandatory.
4. Read [`docs/process.md`](docs/process.md). Pick a role in [`AGENTS.md`](AGENTS.md).
5. Discovery runs catalog → research → shortlist. **No Easy Apply.**
6. Apply and outreach consume packets. Cross-agent talk is **A2A** ([`docs/job-hub/a2a.md`](docs/job-hub/a2a.md)) plus the Hub inbox.

Airgapped bots without a Hub still copy [`profiles/candidate.example.yaml`](profiles/candidate.example.yaml) to `profiles/candidate.yaml` locally, put PDFs in [`assets/resume/`](assets/resume/), and write [`ledger/`](ledger/README.md). Git remains the airgap protocol.

Live multi-agent hunt: [`board/README.md`](board/README.md), [`docs/job-hub/human.md`](docs/job-hub/human.md), [`docs/job-hub/agent.md`](docs/job-hub/agent.md).

## Why this is split

Combined “search and Easy Apply” agents optimize for volume. This template optimizes for **reproducible shortlists**, **attractive applications**, and **human follow-up**.

| Role | Allowed | Forbidden |
| --- | --- | --- |
| Discovery | Find, enrich, score, shortlist, write an apply packet | Easy Apply, form submit, outreach |
| Apply | Submit using the packet, write the message, log proof | Inventing jobs, cold outreach, skipping the packet |
| Outreach | Email + LinkedIn DM after apply (or when there is no portal) | SMS, WhatsApp, spam, applying |
| Maintainer (seldom) | Search registries, vet, write `skills/lists/`, patch example MCP config, **own the hunt board** (tokens, uptime, schema, hygiene) | Discovering jobs, applying, sending mail |

Roles can be subdivided:

- Discovery by portal (Indeed vs YC vs Amazon careers)
- Apply by ATS (Greenhouse vs Workday vs LinkedIn)
- Outreach by channel (email vs LinkedIn DM)
- Maintainer is not subdivided; it is rare and repo-wide

The ledger stays the same. That is the point.

## Architecture in one picture

```mermaid
flowchart TD
  profile[Candidate profile]
  catalog[Skill and MCP catalog]
  research[Deep research]
  discovery[Discovery role]
  ledger[Git ledger airgap]
  board[Hunt board live]
  apply[Apply role]
  outreach[Outreach role]
  maintainer[Maintainer seldom]

  profile --> discovery
  catalog --> discovery
  catalog --> maintainer
  maintainer -->|"skills/lists"| catalog
  maintainer -->|"tokens + uptime"| board
  research --> discovery
  research --> apply
  research --> outreach
  discovery -->|"shortlist + apply packet"| ledger
  discovery --> board
  ledger --> apply
  board --> apply
  apply -->|"applied + outreach packet"| ledger
  apply --> board
  ledger --> outreach
  board --> outreach
  outreach -->|"touches + replies"| ledger
  outreach --> board
```

Full writeup: [`docs/architecture.md`](docs/architecture.md).

## Shared list: git ledger vs live board

Bots may have no shared network except git. The **git ledger is the airgap protocol** (YAML per job). It stays.

When several agents share a host, maintainer runs the **hunt board / Job Hub** as the live coordination UI/API. Discovery/apply/outreach consume it; they do not own it. If `HUB_URL` is set, that is the live list — see [`docs/job-hub/human.md`](docs/job-hub/human.md) (operator) and [`docs/job-hub/agent.md`](docs/job-hub/agent.md) (join, pack, queue). **Maintainer ≠ discovery.**

| Layer | What it is | When to use |
| --- | --- | --- |
| Airgap / template | One YAML file per job under `ledger/jobs/` | Always the file protocol; required if no server |
| Human git view | [`ledger/INDEX.md`](ledger/INDEX.md) | Always in git |
| Git audit | Append-only `ledger/events.jsonl` | Always in git |
| **Live hunt board** | [`board/`](board/README.md) FastAPI + SQLite + admin UI | Shared machine; maintainer-owned |
| Optional overlay | Google Drive / Sheet | Only if someone wants a spreadsheet; not source of truth |

Discovery still owns the **git** ledger portal (conflicts, INDEX, schema). **Maintainer** owns the live board (tokens, uptime, hygiene, tunnels). Details: [`docs/sharing.md`](docs/sharing.md) and [`board/README.md`](board/README.md).

## Skills in this repo

| Skill | Owner | Job |
| --- | --- | --- |
| [`skill-and-mcp-catalog`](skills/skill-and-mcp-catalog/SKILL.md) | Discovery first, maintainer as subroutine | Discover, vet, and add skills/MCPs from any registry |
| [`skill-maintainer`](skills/skill-maintainer/SKILL.md) | Maintainer (seldom) | Search registries, write `skills/lists/`, prune dead tools, own `board/` |
| [`deep-research`](skills/deep-research/SKILL.md) | Shared | Company, people, role, and portal research |
| [`job-discovery`](skills/job-discovery/SKILL.md) | Discovery | Portals, career sites, dorks, shortlist, apply packets |
| [`job-apply`](skills/job-apply/SKILL.md) | Apply | High-quality submit + proof |
| [`job-outreach`](skills/job-outreach/SKILL.md) | Outreach | Email with PDF, LinkedIn DMs, ask for a chat |

Registries are not locked to one marketplace. Use skills.sh, Skills Hub, ClawHub, GitHub, mcp.so, Smithery — whatever you can search, vet, and install. See [`docs/catalogs/skills-and-mcps.md`](docs/catalogs/skills-and-mcps.md).

## Default tool stack

Attach what you have. Degrade if you do not.

| Need | Preferred | Fallback |
| --- | --- | --- |
| Deep research | Exa MCP (`deep_researcher_*`, `agent_run`, company + people search) | Local [dzhng/deep-research](https://github.com/dzhng/deep-research) (`scripts/run_deep_research.py`), Firecrawl, Tavily, Parallel Search MCP (`https://search.parallel.ai/mcp`), built-in web search |
| Job search API | Official Indeed MCP (OAuth) | Public pages + Google dorks |
| YC startups | `uvx workatastartup-mcp==0.1.2` (`bash scripts/mcp/workatastartup.sh`) | workatastartup.com in a browser |
| Remote feed | `https://remoteok.com/api` | RemoteOK site |
| Email + PDF | Gmail MCP draft with `attachments[].content` as base64 | Manual send from the draft |
| Verified contact email | Hunter MCP (`https://mcp.hunter.io/mcp`) | LinkedIn DM only if unverified |
| LinkedIn DM | Logged-in browser / official LinkedIn tools you already have | Copy the DM into the ledger for a human to send |
| Browser apply | Playwright MCP (`@playwright/mcp`) on the apply bot only | Human completes the last submit |
| Public ATS boards | `uvx ats-jobs-mcp==1.0.0` (`bash scripts/mcp/ats-jobs.sh`) | Google dorks + employer careers page |
| Hiring Cafe | `python3 scripts/fetch_hiringcafe.py` | Public hiring.cafe `/jobs/{slug}` page |

Do not scrape behind logins you do not own. Do not build exploit PoCs. Prefer official APIs, public feeds, and career pages.

## Portals this template already names

Job boards and feeds: LinkedIn Jobs, Indeed, Wellfound, Work at a Startup, Google Jobs / dorks, RemoteOK, Hiring Cafe, Weekday, Roro Remote.

Talent networks with little or no public board: Flexiple, Turing, BairesDev, Toptal, Lemon.io. Those are usually **outreach or network-apply**, not Easy Apply.

Big-company career sites: Amazon, Microsoft, Google, Uber, and the rest of the catalog in [`docs/catalogs/big-tech-careers.md`](docs/catalogs/big-tech-careers.md).

Full map: [`docs/catalogs/platforms.md`](docs/catalogs/platforms.md).

## Status contract

```
discovered → enriching → shortlisted → apply_ready → applying → applied
                                                      ↘ apply_blocked
applied → outreach_ready → outreaching → waiting → chatting → interview → offer
         ↘ skipped / closed_rejected / closed_withdrawn / closed_expired
```

Discovery may set `skipped`. Apply may set `apply_blocked` with a reason and a packet update. Outreach never silently rewrites a job’s title, company, or apply URL.

## What “good” looks like

- Discovery output is a **packet** another bot can apply from tomorrow with no chat history.
- Apply output is a message a hiring manager might actually finish reading, plus proof of submit.
- Outreach output is a short email with the PDF attached, a LinkedIn DM asking for a chat, and a logged touch.
- The ledger is the only memory that matters.

## Repo layout

```
AGENTS.md                 How a bot picks a role and behaves
docs/process.md           The full contract
docs/architecture.md      Components and data flow
docs/roles.md             Split / combine / subdivide roles
docs/sharing.md           Airgapped ledger protocol
docs/catalogs/            Platforms, MCPs, career sites, research
docs/research/            Build plans (MCP coverage, deep-research wrap)
skills/                   Agent Skills (SKILL.md) — canonical OS skills
.agents/skills/           Downloaded third-party Agent Skills (npx skills add)
.claude/skills/<name>     Per-skill symlink for Claude Code
.cursor/skills/<name>     Per-skill symlink for Cursor
skills/lists/             Maintainer lists: adopted / wanted / rejected YAML
board/                    Live hunt board (FastAPI + SQLite). Maintainer-owned.
vendor/mcp/PINNED.txt     uvx / git SHA pins for local MCPs (no source trees)
mcp/hosted/               Copy-paste hosted MCP snippets
mcp/SETUP.md              How to attach local vs hosted MCPs
.cursor/environment.json  Cloud-agent install (clones open-deep-research)
.github/workflows/        CI on PR; Deploy on push to main (this host)
docs/deploy.md            Host deploy (Actions runner + watcher)
docs/demo/                Screenshots + video of the live Hub
ledger/                   Shared live list
profiles/                 Candidate profile (example committed)
mcp/                      Example MCP config
handoffs/                 Packet templates
assets/                   Resumes (local) + writing templates
scripts/rebuild_index.py  Optional INDEX.md generator
scripts/rebuild_skill_index.py  skills/lists/INDEX.md from YAML
scripts/setup_deep_research.sh  Clone dzhng/open-deep-research
scripts/run_deep_research.py    Non-interactive research API wrapper
```

## Run a cycle

```bash
# optional, if uv is available
uv run scripts/rebuild_index.py
uv run scripts/rebuild_skill_index.py

# live hunt board (maintainer): generates gitignored tokens on first start
bash board/start.sh
```

Then, in the agent:

- Discovery: “Run the discovery skill for this candidate. Do not apply.”
- Apply: “Apply only to jobs in apply_ready. Write like a human worth reading.”
- Outreach: “Work outreach_ready. Email + LinkedIn only. Attach the PDF on email.”
- Maintainer (seldom): “Refresh skills/lists. Find MCPs. Do not discover jobs.” Owns the hunt board: tokens, uptime, hygiene.

## Public template

This repo is meant to be copied, then maintained. Keep process changes in `docs/`, keep skill instructions executable, keep live candidate data out of git.

License: [MIT](LICENSE).
