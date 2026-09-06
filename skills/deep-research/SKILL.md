---
name: deep-research
description: Company, people, role, and portal research for Job Apply OS using Exa deep research when available, else local dzhng/open-deep-research, Firecrawl, Tavily, or built-in web search. Use before shortlisting, before writing an application, and before outreach to hiring managers or teammates. Produces short cited briefs, not essays.
---

# Deep research

Shared skill. You do not own jobs. You return briefs other roles paste into the ledger.

## Stack (use the first that exists)

1. Exa MCP — `deep_researcher_start` / `deep_researcher_check`, `agent_run`, `company_research_exa`, `linkedin_search_exa`, `web_search_advanced_exa`, `crawling_exa`
2. Local [dzhng/deep-research](https://github.com/dzhng/deep-research) via `python3 scripts/run_deep_research.py` when Exa is missing and Firecrawl + OpenAI/Fireworks keys exist
3. Firecrawl agent / scrape
4. Tavily
5. Built-in WebSearch and WebFetch

Read `docs/catalogs/deep-research.md` for tool notes and the local runner. If Exa is present, **use it** for shortlist and outreach people-finding. Do not only keyword-search when a deep research tool exists.

## Local runner (cloud agent)

`.cursor/environment.json` clones the repo into `agent-tools/open-deep-research` on install.

```bash
bash scripts/setup_deep_research.sh
python3 scripts/run_deep_research.py \
  --query "<specific instruction>" \
  --depth 2 --breadth 3 \
  --brief-out ledger/.cache/research-brief.md
```

`npm start` is interactive. Do not use it in this environment. The wrapper hits `POST /api/research`. Compress the JSON into the catalog brief; do not commit reports or keys.

## Modes

### Posting check (discovery)

Is this URL a live job? Who is the company? Any freeze / scam signals?

### Company brief (apply)

One true product or team fact, sourced, for a letter.

### People map (outreach)

Hiring manager, recruiter, one teammate, founder only if small. LinkedIn URLs. Email only if verified or labeled `confidence: low` and not sent.

## Method

1. Write a specific instruction, not “research the company.”
2. If you start `deep_researcher_*`, poll until complete. Do not abandon the task id.
3. If you start the local runner, wait for JSON (it is blocking). Default depth 2.
4. Cite URLs in the brief.
5. Compress into the YAML shape in the catalog doc.
6. If sources conflict, say so. Do not average them into a fake certainty.

## Quality

- No invented emails or headcount
- No “culture fit” poetry
- Prefer primary sources: careers page, posting, official blog, LinkedIn
