# Research to build: platform MCP coverage + deep-research

Date: 2026-09-06. Actor: catalog + research (discovery-adjacent). **No applications.**

This is an implementation plan for Job Apply OS, not an essay. It maps each named platform to a concrete tool, says what to add, and lists the next patches in order.

Related:

- Inventory: [`docs/catalogs/skills-and-mcps.md`](../catalogs/skills-and-mcps.md)
- Research runner: [`docs/catalogs/deep-research.md`](../catalogs/deep-research.md)
- Process: [`docs/process.md`](../process.md)

## What already landed in this change

These are done; do not redo them.

1. Cloud-agent wiring for [dzhng/deep-research](https://github.com/dzhng/deep-research): `.cursor/environment.json` `install` → `scripts/setup_deep_research.sh` clones into gitignored `agent-tools/open-deep-research`. Wrapper: `scripts/run_deep_research.py`.
2. `skills/deep-research/SKILL.md` stack now has the local runner as #2 after Exa.
3. Catalog pass (skills.sh, Skills Hub, GitHub, PyPI, vendor docs) written into the inventory.

Still missing for a live cycle: a truthful `profiles/candidate.yaml` (only the gitignored example copy exists), resume PDFs, and research API keys.

## Architecture of dzhng/deep-research (what we wrap)

Upstream package `open-deep-research`, Node 22, MIT.

```
query + breadth + depth
        │
        ▼
  generate SERP queries (LLM / o3-mini or Fireworks R1)
        │
        ▼
  Firecrawl search + markdown scrape (concurrency 2)
        │
        ▼
  extract learnings + follow-up questions
        │
        ▼
  depth > 0? ──yes──► recurse (breadth = ceil(breadth/2))
        │ no
        ▼
  writeFinalAnswer | writeFinalReport + visitedUrls
```

Two entrypoints:

| Entry | Job Apply OS |
| --- | --- |
| `npm start` → `src/run.ts` | **Do not use in cloud agents** (stdin prompts) |
| `npm run api` → `POST /api/research` | **Use this.** Wrapper already calls it |
| `POST /api/generate-report` | **Do not use.** Upstream returns raw markdown from the handler instead of `res.json` |

Not an MCP. Do not add it to `mcp.json`. Keep it as a local binary the research skill shells out to.

**Do not git-submodule it.** The repo is a teaching artifact (maintenance slowed after mid-2025). Pin by shallow clone + `git reset --hard FETCH_HEAD` on each environment install so we can drop it if Exa covers the cycle.

## Target stack after the next implementation pass

Discovery bot (needs network):

| Capability | Install | Role env |
| --- | --- | --- |
| Exa MCP | Cursor dashboard HTTP `https://mcp.exa.ai/mcp?tools=...` | discovery |
| Firecrawl MCP | `npx -y firecrawl-mcp` + `FIRECRAWL_API_KEY` | discovery |
| Tavily MCP | remote URL or `npx -y tavily-mcp@latest` | discovery (optional) |
| Indeed MCP | Claude/Cursor connector when the client supports it | discovery |
| workatastartup-mcp | `uvx workatastartup-mcp` | discovery |
| ats-jobs-mcp | `uvx ats-jobs-mcp` | discovery |
| RemoteOK | `curl` / WebFetch, no MCP | discovery |
| open-deep-research | already cloned by environment install | discovery |
| Playwright MCP | **not** on discovery | — |

Apply bot:

| Capability | Install |
| --- | --- |
| Playwright MCP `npx @playwright/mcp@latest` | greenhouse / lever / workday / linkedin easy apply |
| Packet + profile only | airgap OK for writing |

Outreach bot:

| Capability | Install |
| --- | --- |
| Gmail MCP (already on this cloud agent) | drafts with PDF |
| Drive MCP (already on) | proof PDFs overlay |
| Calendar MCP (already on) | interview times |
| Hunter MCP `https://mcp.hunter.io/mcp` | verify emails |
| Playwright or LinkedIn session tools | DMs only, no InMail blast |

## Per-platform build steps

### LinkedIn

**Gap:** no official jobs MCP.

1. Discovery: WebSearch + public `/jobs` URLs, or (human opt-in) stickerdaniel server with **job tools only**.
2. Add a Cursor MCP entry named `linkedin-discovery` that allowlists `search_jobs`, `get_job_details`, `search_people`. Put it in the discovery environment, not outreach.
3. Apply: packet `apply_kind: linkedin_easy_apply` → Playwright on the apply bot. Never from discovery.
4. Outreach: short DM via Playwright or human paste. Templates already in `assets/templates/linkedin-dm.md`.
5. Do not install prakharagarwal-dev server as-is (search + messaging + posting).

### Indeed

1. Human: add Indeed connector if Cursor exposes it. Endpoint: `https://mcp.indeed.com/claude/mcp`.
2. If attach fails (likely — docs say Claude Connector), keep public URL + dorks. Log `blocked: indeed mcp client` in the catalog, not in a fake job.
3. Map MCP Job Detail → `ledger/jobs/indeed__<jobid>.yaml`.

### Wellfound

1. No official MCP. Discovery uses the public site + Exa crawl of a known job URL.
2. Do not add Apify Wellfound scrapers unless the user accepts ToS risk in writing.
3. Dedup against LinkedIn (`(company, title, location)`).

### Work at a Startup

1. Add to `mcp/mcp.local.json` (gitignored copy of example):

```json
"workatastartup": {
  "command": "uvx",
  "args": ["workatastartup-mcp"]
}
```

2. Discovery loop: `search_jobs` with candidate titles → `get_job_details` → packet with apply URL.
3. Do not use the cookie-session fork.

### Google Jobs + ATS dorks

1. Keep dorks in `platforms.md`. Run them through Exa `web_search_advanced_exa` or WebSearch.
2. Add `ats-jobs-mcp` for named companies the candidate cares about (`list_open_jobs` on Greenhouse/Ashby/Lever boards). This is the highest-leverage missing discovery MCP.

```json
"ats-jobs": { "command": "uvx", "args": ["ats-jobs-mcp"] }
```

3. Always store `verify_url` from the employer board, not a Google card.

### RemoteOK

1. No MCP. `GET https://remoteok.com/api` (and `?tag=`). Skip index 0.
2. Optional later: a 20-line `scripts/fetch_remoteok.py` that writes `discovered` YAML. Not required for v1.

### Weekday / Roro Remote

1. Weekday: public pages. First cycle: WebFetch `https://jobs.weekday.works` + dorks. Record whether listings are Workable.
2. Roro Remote: still unconfirmed URL. First discovery actor searches the web, then either adds a board URL to `platforms.md` or marks `outreach_only`.

### Talent networks (Flexiple, Turing, Toptal, Lemon.io, BairesDev)

1. One job file per network, `apply_kind: network`.
2. Apply role uses Playwright to run the documented intake. No MCP exists; do not invent one.
3. Outreach seed is part of the packet (process §3.2).

### Big-company career sites

1. Dorks + Playwright. Amazon needs req id in the packet.
2. `ats-jobs-mcp` covers some (Stripe/Cloudflare Greenhouse, Anthropic/Anduril Ashby) when the board slug is known.
3. Outreach policy stays `teammates_and_recruiter`. Hunter for recruiter email only when verified.

## Mail, calendar, Drive (already here)

This cloud agent already has Gmail, Drive, and Calendar MCPs.

| Next patch | Owner | Detail |
| --- | --- | --- |
| Outreach skill: refuse send without attachment | outreach | Already written; keep testing `create_draft` with a real PDF once `assets/resume/` exists |
| Drive overlay optional script | discovery | If `GOOGLE_DRIVE_LEDGER_FOLDER_ID` is set, copy proof PDFs after apply. Git still wins |
| Calendar | outreach | Only after `interview` or an explicit time proposal. `suggest_time` then `create_event` |
| Official Google remote MCPs | anyone on a non-Cursor client | Documented in the catalog. Do not duplicate Gmail servers on this agent |

## Marketing / outreach that helps applications land

In scope (helps a **specific** applied job):

1. Hunter verify → Gmail draft with PDF (required).
2. LinkedIn DM asking for a 15-minute chat.
3. Optional copy skill `compose-outreach` / `draft-outreach` if Common Room is not required — otherwise keep `assets/templates/email.md`.
4. Calendar once they reply.

Out of scope unless the user adds the channel:

- Smartlead / Instantly / Apollo **sequences**
- SMS, WhatsApp, InMail blasts
- LinkedIn content mills / profile optimizers
- Sales “hiring signal” composites

Apollo MCP may be added for **people search + enrichment only**. Put sequence tools on a deny list in the outreach environment.

## Supporting skills (not resume curation)

Install later if a cycle is blocked:

| Skill | Why |
| --- | --- |
| firecrawl-deep-research | Only when the human wants a long report. Not the default brief |
| googleworkspace/cli `gws-gmail*` | CLI fallback if Gmail MCP dies |
| `gws-calendar*` | Same for Calendar |
| Playwright MCP | Apply + DM |

Do not install resume-optimizer / LinkedIn ghostwriting skills.

## Gaps that stay gaps (do not fake a tool)

- Official LinkedIn Jobs MCP
- Official Wellfound MCP
- Indeed on Cursor (unverified)
- Weekday, Roro, Flexiple, Turing, Toptal, Lemon.io, BairesDev MCPs
- A maintained MCP wrapper around dzhng/deep-research (write one only if Exa stays unauthenticated **and** operators run the CLI weekly)

## Recommended next implementation order

Do these as separate PRs. Discovery still must not Easy Apply.

1. **Human secrets (blocker for a live cycle)**  
   Fill `profiles/candidate.yaml`, drop resume PDFs in `assets/resume/`, put `EXA_API_KEY` or `FIRECRAWL_KEY`+`OPENAI_KEY`, and `HUNTER_API_KEY` in the cloud-agent secret store. Not a code change.

2. **Attach discovery MCPs in Cursor dashboard**  
   Exa (required for preferred path), Firecrawl, workatastartup-mcp, ats-jobs-mcp. Indeed if the connector appears. Gmail/Drive/Calendar are already on this agent.

3. **`scripts/fetch_remoteok.py` (small)**  
   Map RemoteOK JSON → `ledger/jobs/remoteok__<id>.yaml` + event line. Dedup by apply URL.

4. **Discovery loop smoke (no apply)**  
   One cycle: YC MCP + RemoteOK + one ATS company via ats-jobs-mcp + dorks. Write packets. Stop.

5. **Hunter on outreach env**  
   Add `https://mcp.hunter.io/mcp` with API key header. Teach outreach skill: verify → draft. Already described; needs auth.

6. **Playwright on apply env only**  
   `mcp.example.json` already has a slot after this PR. Do not put Playwright on the discovery cloud agent.

7. **LinkedIn discovery opt-in**  
   Only after the human says they will keep a logged-in session. Fork stickerdaniel config with a tool allowlist.

8. **Optional: thin MCP shim for open-deep-research**  
   Stdio server exposing `deep_research_local({query, depth, breadth})` that shells to `scripts/run_deep_research.py`. Only if operators dislike the CLI. Not needed for v1.

## How it plugs into the existing process

```
catalog (this doc + skills-and-mcps.md)
    → deep-research (Exa, else local dzhng, else Firecrawl/Tavily/search)
    → job-discovery (platforms.md methods; MCPs where vetted)
    → ledger apply_packet
    → job-apply (Playwright / ATS)          # later cycle
    → job-outreach (Gmail+PDF, LinkedIn DM, Hunter, Calendar)
```

No fourth owner. Research stays a capability.

## Verification for this PR (no live research run)

Live `POST /api/research` was **not** executed: `FIRECRAWL_KEY` and `OPENAI_KEY` are absent. What was verified:

- Upstream README, `package.json`, `src/run.ts`, `src/api.ts`, `src/deep-research.ts`, `src/ai/providers.ts` from a shallow clone of `dzhng/deep-research`
- `python3 scripts/run_deep_research.py --help` (after this PR)
- Registry queries listed in the catalog workspace log
- Gmail `create_draft` schema on this agent includes `attachments[].content` base64
