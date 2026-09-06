# Deep research

Shared capability for all three roles. Preferred MCP: **Exa**. Local fallback the cloud agent can run: **[dzhng/deep-research](https://github.com/dzhng/deep-research)** (Open Deep Research). Not unique to Skillhub or any one portal.

## Why it is in the template

Discovery without research dumps stale links. Apply without research writes generic letters. Outreach without research emails the wrong person and cannot attach a reason to exist.

## Preferred stack

Use the first that exists. Do not skip a working Exa MCP to run the local CLI.

### 1. Exa MCP (default)

Remote MCP: `https://mcp.exa.ai/mcp`

Enable the research tools explicitly (defaults are narrower):

```
https://mcp.exa.ai/mcp?tools=web_search_exa,web_search_advanced_exa,company_research_exa,linkedin_search_exa,deep_researcher_start,deep_researcher_check,agent_run,crawling_exa
```

OAuth login: `https://mcp.exa.ai/mcp?login` if the client supports it. Else `EXA_API_KEY`.

| Tool | Use |
| --- | --- |
| `web_search_exa` | Fast lookup |
| `web_search_advanced_exa` | Date/domain filters, ATS dorks |
| `company_research_exa` | Company brief |
| `linkedin_search_exa` | People / company on LinkedIn index |
| `deep_researcher_start` + `deep_researcher_check` | Multi-step report; poll until complete |
| `agent_run` | List-building, enrichment, structured output |
| `crawling_exa` | Extract a known URL |

Start deep research with a **specific instruction**, then immediately check the task id until `completed`.

Source: [exa-labs/exa-mcp-server](https://github.com/exa-labs/exa-mcp-server).

### 2. Local `dzhng/deep-research` (cloud-agent wired)

Upstream: [dzhng/deep-research](https://github.com/dzhng/deep-research) (MIT, TypeScript, ~500 LoC, npm name `open-deep-research`).

This is **not** an MCP. It is a recursive Firecrawl + LLM loop with an HTTP API. Job Apply OS clones it into gitignored `agent-tools/open-deep-research` during cloud-agent `install` (see `.cursor/environment.json`).

**How it works**

1. LLM generates SERP queries from the instruction (breadth = queries per round).
2. Firecrawl `search` + markdown scrape.
3. LLM extracts learnings + follow-up directions.
4. Recurse while depth > 0 (breadth halves each level).
5. Compile `answer` / `report.md` plus visited URLs.

**Keys (never commit)**

Upstream `.env.local` names, with Job Apply OS aliases:

| Upstream | Also accepted by `scripts/run_deep_research.py` |
| --- | --- |
| `FIRECRAWL_KEY` | `FIRECRAWL_API_KEY` |
| `OPENAI_KEY` | `OPENAI_API_KEY` |
| `FIREWORKS_KEY` | `FIREWORKS_API_KEY` (switches model to DeepSeek R1) |
| `OPENAI_ENDPOINT` + `CUSTOM_MODEL` | OpenAI-compatible endpoint (OpenRouter, local, Gemini) |
| `FIRECRAWL_BASE_URL` | Self-hosted Firecrawl |
| `FIRECRAWL_CONCURRENCY` | Default 2; free Firecrawl should stay at 1–2 |

Needs **Node 22**. Interactive `npm start` is the upstream UX. Cloud agents **must not** use that — it waits on stdin. Use the HTTP API.

**Operator run (this cloud agent)**

```bash
bash scripts/setup_deep_research.sh   # idempotent clone + npm ci
# FIRECRAWL_KEY and OPENAI_KEY must already be in the environment
python3 scripts/run_deep_research.py \
  --query "Is <company> still hiring <role>? Cite careers URL, team, red flags." \
  --depth 2 --breadth 3 \
  --brief-out ledger/.cache/research-brief.md
```

Then compress into the YAML shape below. Do not paste the full `report.md` into a job file.

**API contract we wrap**

- `POST http://127.0.0.1:3051/api/research` `{ query, depth, breadth }` → `{ success, answer, learnings, visitedUrls }`
- Do **not** call `/api/generate-report` from the wrapper: upstream returns the markdown as the Express response instead of `res.json`, so clients hang or mis-parse.

**Fit vs Exa**

| Need | Exa | dzhng local |
| --- | --- | --- |
| Company + people index | Yes (`company_research_exa`, `linkedin_search_exa`) | No (SERP only) |
| Async pollable task | Yes | No (blocking HTTP) |
| Airgapped except Firecrawl/OpenAI | No | Yes |
| Structured Job Apply OS brief | You compress | You compress (script writes a stub) |

Default depth 2 / breadth 3. Higher values burn Firecrawl credits and time. Skip this runner for obvious spam postings.

### 3. Firecrawl MCP

Best when you already have a URL: JD page, careers listing, about page. `agent` tool for multi-source extraction. Use as fallback when Exa is missing and you do not want to start the local API.

Official server: `npx -y firecrawl-mcp` with `FIRECRAWL_API_KEY`. Repo: [firecrawl/firecrawl-mcp-server](https://github.com/firecrawl/firecrawl-mcp-server).

Related skill (report-scale only, not a discovery default): `npx skills add https://github.com/firecrawl/firecrawl-workflows --skill firecrawl-deep-research`.

### 4. Tavily

Fast LLM-ready search. Good when you only need confirmation (“is this req still live?”).

Remote: `https://mcp.tavily.com/mcp/?tavilyApiKey=<key>` or `npx -y tavily-mcp@latest` with `TAVILY_API_KEY`. Docs: https://docs.tavily.com/documentation/mcp

### 5. Built-in WebSearch / WebFetch

Airgapped-from-paid-keys mode. Still enough for dorks and public careers pages.

## Role recipes

### Discovery

Question: is this job real, current, and a fit?

Output into the job YAML:

```yaml
research:
  posting_live: true
  last_checked: "2026-09-06"
  company_one_liner: ""
  red_flags: []
  team_guess: ""
  sources: []
```

Skip deep_researcher / local recursive runs for obvious spam. Use them for shortlist candidates.

### Apply

Question: what one true detail makes the letter specific?

Allowed: product name, recent launch, team mission **from the JD or a cited source**.
Forbidden: invented metrics, fake “I’ve used your API internally.”

### Outreach

Question: who should we talk to, and what is the ask?

Find, in order:

1. Recruiter or HM named on the posting
2. Someone with the same title on the team
3. Founder only if the company is small

Store people in `ledger/people/` with URLs, not just names. Never guess an email pattern and send. If you cannot find a verified or high-confidence email, LinkedIn DM only. Prefer Hunter MCP (`https://mcp.hunter.io/mcp`) or Apollo enrichment for verification — see the catalog.

## Brief format (keep it short)

```md
# Research brief: <company> / <role>
- Live?: yes/no (<url>)
- What they do: one sentence
- Why the candidate: one sentence from profile
- People: name — title — linkedin — email if verified
- Risks: stale posting / hiring freeze rumor / mismatch
- Sources: urls
```

Paste a compressed version into the job YAML. Do not dump ten pages of model prose into the ledger.

## Cloud-agent notes (this workspace, 2026-09-06)

- `.cursor/environment.json` `install` runs `scripts/setup_deep_research.sh`.
- Clone lives in gitignored `agent-tools/open-deep-research` (not a git submodule).
- This run's environment is still a personal dashboard snapshot (`environmentJsonPath` was null). After this file lands on `main`, new cloud agents that boot from the repo file will run the install script.
- Keys are **not** in the repo. If they are missing, degrade to WebSearch/WebFetch and write `blocked: research keys` on the job — do not invent sources.
