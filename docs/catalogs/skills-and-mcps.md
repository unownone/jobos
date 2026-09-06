# Skills and MCPs

This file is the **workspace inventory**. Discovery refreshes it. Anyone can add a row after vetting.

Do not lock to one marketplace. Search, vet, then add.

## Where to look (in order)

| Registry | What it is | How to search | How to install |
| --- | --- | --- | --- |
| [skills.sh](https://skills.sh) + `npx skills` | Agent Skills directory | `npx skills find "linkedin jobs"` | `npx skills add <owner/repo> --skill <name>` |
| [skills-hub.ai](https://skills-hub.ai) | Skill hub CLI | `npx @skills-hub-ai/cli search "job discovery"` | `npx @skills-hub-ai/cli install <name> --target cursor` |
| [ClawHub](https://clawhub.ai) | OpenClaw skills | site search / `clawhub` | `clawhub install <slug>` |
| GitHub | Raw `SKILL.md` repos | `path:SKILL.md linkedin jobs` | copy into `skills/` or `npx skills add` |
| [mcp.so](https://mcp.so) / Smithery / Glama | MCP servers | “indeed mcp”, “exa mcp” | client `mcp.json` |
| Official vendor docs | Indeed, Exa, Firecrawl, Gmail | vendor site | vendor URL + OAuth |

If a registry is down, skip it and note the miss. The catalog skill is done when **at least two** registries were queried or honestly unavailable.

## Vet rubric

Score 1–5. Install only at 4+ unless the user overrides.

| Check | Fail |
| --- | --- |
| License / source visible | Unclear binary, no repo |
| Scope | Skill applies and discovers in one breath with no stop flag |
| Auth | Wants passwords in chat, cookie dumping without a warning |
| ToS | Explicitly bypasses LinkedIn/Indeed anti-bot as the product |
| Airgap | Requires a hosted account we cannot provide and has no file mode |
| Quality | Empty SKILL.md, no steps, only marketing |

Auto-apply skills may be listed for the **apply** role. They must not be enabled on discovery.

## Required in this template

These are the defaults the three skills expect. Swap implementations, keep the *capability*.

| Capability | Default | Config | Used by |
| --- | --- | --- | --- |
| Deep research | Exa MCP | `https://mcp.exa.ai/mcp?tools=web_search_exa,web_search_advanced_exa,company_research_exa,linkedin_search_exa,deep_researcher_start,deep_researcher_check,agent_run,crawling_exa` | all |
| Extraction fallback | Firecrawl MCP | official Firecrawl MCP / `FIRECRAWL_API_KEY` | discovery, research |
| Fast search fallback | Tavily or built-in WebSearch | `TAVILY_API_KEY` | all |
| Indeed jobs | Official Indeed MCP (OAuth) | Claude connector or compatible client; see Indeed partner docs | discovery |
| YC jobs | `workatastartup-mcp` | `uv` / pip package `workatastartup-mcp` | discovery |
| Remote feed | HTTP GET | `https://remoteok.com/api` | discovery |
| Email + PDF | Gmail MCP `create_draft` | attachments: filename, mimeType `application/pdf`, content base64 | outreach |
| Files overlay | Google Drive MCP | optional folder | discovery portal |
| Browser apply | Playwright / computer-use | apply bot only | apply, linkedin dm |

Example client config: [`mcp/mcp.example.json`](../../mcp/mcp.example.json).

## Known skill families to evaluate (not auto-installed)

Record verdicts here when you look at them. Examples that exist in the wild:

- LinkedIn job discovery / LinkedIn Easy Apply skills (apply role only)
- Job-hunter / job-finder skills that search multiple boards
- `job-auto-apply` style combined agents — **split them**; do not run as discovery
- Resume tailoring skills that forbid fabrication — useful for apply
- LinkedIn MCP servers — check whether they are official OAuth or session-cookie based before enabling

When you vet one, append:

```md
### <name>
- source:
- capability:
- role: discovery | apply | outreach | research | catalog
- verdict: use / fork / reject
- notes:
```

## Workspace log

_Copy this section into your live fork and keep it current._

| date | actor | queried | added | rejected |
| --- | --- | --- | --- | --- |
| 2026-09-06 | template | skills.sh, skills-hub.ai, GitHub, Indeed docs, Exa docs | Exa deep research, Indeed MCP, workatastartup-mcp, RemoteOK API, Gmail attachments | combined auto-apply as discovery |

## Indeed MCP notes

Official docs: https://docs.indeed.com/mcp/

- Remote MCP, Streamable HTTP, OAuth with an Indeed account
- Tools: Job Search, Job Detail, Get Resume, Get Company Data
- Availability can be connector-limited (historically Claude connector). If Cursor cannot attach it, discovery uses public Indeed URLs + dorks and writes that limitation here.

## Gmail PDF attachments

Outreach has been failing this in the wild when the agent sends `body` only.

Correct draft shape (conceptually):

- `to`, `subject`, `body` and/or `htmlBody`
- `attachments`: `{ filename: "Ada-Example-Resume.pdf", mimeType: "application/pdf", content: "<base64>" }`

Read the PDF from `assets/resume/`, base64 it, then create the draft. If the tool errors, stop and mark the touch `blocked: attachment`. Do not send without the file.
