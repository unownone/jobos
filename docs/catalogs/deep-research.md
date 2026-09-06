# Deep research

Shared capability for all three roles. Preferred MCP: **Exa**. Not unique to Skillhub or any one portal.

## Why it is in the template

Discovery without research dumps stale links. Apply without research writes generic letters. Outreach without research emails the wrong person and cannot attach a reason to exist.

## Preferred stack

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

### 2. Firecrawl MCP

Best when you already have a URL: JD page, careers listing, about page. `agent` tool for multi-source extraction. Use as fallback when Exa is missing.

### 3. Tavily

Fast LLM-ready search. Good when you only need confirmation (“is this req still live?”).

### 4. Built-in WebSearch / WebFetch

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

Skip deep_researcher for obvious spam. Use it for shortlist candidates.

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

Store people in `ledger/people/` with URLs, not just names. Never guess an email pattern and send. If you cannot find a verified or high-confidence email, LinkedIn DM only.

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
