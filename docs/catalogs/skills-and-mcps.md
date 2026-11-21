# Skills and MCPs

GitHub OS skills (`skills/*/SKILL.md`) and tagged starters (`skills/starters/`) are the **defaults**. When Hub is up, the **live inventory for agents** is the Hub registry (`GET /api/registry/skills`). Contract: [`skill-outline.md`](skill-outline.md).

This file plus [`skills/lists/`](../../skills/lists/) still track MCP/tools **adopted / wanted / rejected**. Discovery refreshes this catalog. Maintainer writes the machine-readable lists. Anyone can add a row after vetting.

Do not lock to one marketplace. Search, vet, then add.

**Last catalog pass:** 2026-09-15 (this week). **Last maintainer pass:** 2026-09-15 — Hub registry + memory solidify e2e; lists unchanged from 2026-09-06.

Build plan (what to install next, in order): [`docs/research/platform-mcp-build-plan.md`](../research/platform-mcp-build-plan.md).

## Where to look (in order)

| Registry | What it is | How to search | How to install |
| --- | --- | --- | --- |
| [skills.sh](https://skills.sh) + `npx skills` | Agent Skills directory | `npx skills find "linkedin jobs"` | `npx skills add <owner/repo> --skill <name>` |
| [skills-hub.ai](https://skills-hub.ai) | Skill hub CLI | `npx @skills-hub-ai/cli search "job discovery"` | `npx @skills-hub-ai/cli install <name> --target cursor` |
| [ClawHub](https://clawhub.ai) | OpenClaw skills | site search / `clawhub` | `clawhub install <slug>` |
| GitHub | Raw `SKILL.md` repos | `path:SKILL.md linkedin jobs` | copy into `skills/` or `npx skills add` |
| [mcp.so](https://mcp.so) / Smithery / Glama | MCP servers | “indeed mcp”, “exa mcp” | client `mcp.json` |
| Official vendor docs | Indeed, Exa, Firecrawl, Gmail, Hunter, Apollo | vendor site | vendor URL + OAuth |

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
| Recursive local research | dzhng/open-deep-research | `bash scripts/setup_deep_research.sh` then `python3 scripts/run_deep_research.py` (`FIRECRAWL_KEY` + `OPENAI_KEY`) | research |
| Extraction fallback | Firecrawl MCP | `npx -y firecrawl-mcp` / `FIRECRAWL_API_KEY` | discovery, research |
| Fast search fallback | Tavily or Parallel Search MCP | `TAVILY_API_KEY` or `https://search.parallel.ai/mcp` (no key on free tier) | all |
| Indeed jobs | Official Indeed MCP (OAuth) | `https://mcp.indeed.com/claude/mcp` — Claude connector historically | discovery |
| YC jobs | `workatastartup-mcp` | PyPI `workatastartup-mcp` 0.1.2 ([MIt9/workatastartup-mcp](https://github.com/MIt9/workatastartup-mcp)) | discovery |
| Public ATS boards | `ats-jobs-mcp` | `pip install ats-jobs-mcp` ([groundtruthtools/ats-jobs-mcp](https://github.com/groundtruthtools/ats-jobs-mcp)) | discovery |
| Remote feed | HTTP GET | `https://remoteok.com/api` | discovery |
| Email + PDF | Gmail MCP `create_draft` | attachments: filename, mimeType `application/pdf`, content base64 | outreach |
| Files overlay | Google Drive MCP | optional folder | discovery portal |
| Calendar | Google Calendar MCP | interview slots after `chatting` / `interview` | outreach |
| Verified email | Hunter MCP | `https://mcp.hunter.io/mcp` + `X-API-Key` | outreach, research |
| Browser apply | Playwright MCP | `npx @playwright/mcp@latest` — **apply bot only** | apply, linkedin dm |

Example client config: [`mcp/mcp.example.json`](../../mcp/mcp.example.json).

## This cloud agent (already attached)

Queried 2026-09-06 via Cursor dynamic MCP namespaces. Do not re-auth unless a tool errors.

| Namespace | Status | Job Apply OS use |
| --- | --- | --- |
| Gmail | ready | Outreach drafts with PDF attachments; `create_draft.attachments[].content` is base64 |
| Google-drive | ready | Optional ledger overlay (git remains canonical) |
| Google-calendar | ready | Suggest interview times; do not book until the human asks |
| cursor-cloud | ready | Environment / run diagnostics only |

These are Cursor-hosted Google Workspace MCPs. Self-hosted clients can instead use Google's remote endpoints (`gmailmcp.googleapis.com`, `drivemcp.googleapis.com`, `calendarmcp.googleapis.com`) per [Google Workspace MCP docs](https://developers.google.com/workspace/guides/configure-mcp-servers).

## Capability matrix (platforms this OS already names)

Legend: **D** discovery, **R** research / hiring-manager lookup, **M** mail, **O** outreach/marketing, **A** apply-adjacent. Verdict: use / fork / reject / gap.

| Platform | Tool | D | R | M | O | A | Verdict | Auth / install | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LinkedIn Jobs | No official MCP | | | | | | **gap** | User session | List/packet only. Easy Apply is apply-role |
| LinkedIn Jobs | [stickerdaniel/linkedin-mcp-server](https://github.com/stickerdaniel/linkedin-mcp-server) | y | y | | y | | **fork** | Logged-in browser session | `search_jobs`, `get_job_details`, `search_people` OK for discovery **if the human owns the session**. Disable `send_message` / connection tools on discovery bots. Cookie/session product — ToS risk; warn the human |
| LinkedIn Jobs | [prakharagarwal-dev/linkedin-mcp-server](https://github.com/prakharagarwal-dev/linkedin-mcp-server) | y | y | | y | y | **reject** as discovery | Playwright + session | Combines search, publish, and messaging. Split or do not enable on discovery |
| LinkedIn people | Exa `linkedin_search_exa` | | y | | | | **use** | Exa OAuth / API key | Index search, not a LinkedIn login |
| LinkedIn DM | Playwright MCP or human paste | | | | y | | **use** | Logged-in browser on outreach bot | No PDF on DMs. Ask for a 15-minute chat |
| LinkedIn skills.sh | `linkedin-job-scraper` (JobSpy) | y | | | | | **fork** | `python-jobspy` | Scraping library; do not treat as official API |
| LinkedIn skills.sh | `linkedin-profile-optimizer`, `linkedin-posts`, `linkedin-ghostwriting` | | | | y | | **reject** for this OS | | User said no resume/profile curation. Posts are marketing-for-content, not application outreach |
| Indeed | Official Indeed MCP | y | y | | | | **use** | Indeed OAuth; Claude connector | Tools: Job Search, Job Detail, Get Resume, Get Company Data. Docs: https://docs.indeed.com/mcp/ . Cursor attach is unproven — fall back to public URLs |
| Wellfound | No official MCP | y | | | | | **gap** | Session optional | Site search. Apify scrapers exist; treat as ToS-sensitive, not default |
| Work at a Startup | `workatastartup-mcp` 0.1.2 | y | y | | | | **use** | none | `uvx workatastartup-mcp` / `pip install workatastartup-mcp`. Tools: `search_jobs`, company + job detail. Public YC board |
| Work at a Startup | [moutasem-isentemiz/workatastartup-mcp](https://github.com/moutasem-isentemiz/workatastartup-mcp) | y | | | | | **reject** default | `WAAS_COOKIE` | Cookie-session fork. Prefer the PyPI public server |
| Google Jobs | Built-in WebSearch | y | | | | | **use** | none | Always store the employer apply URL, not the Google card |
| Google ATS dorks | Exa advanced search / WebSearch | y | | | | | **use** | none | Operators in `platforms.md` |
| Greenhouse / Ashby / Lever | `ats-jobs-mcp` | y | | | | | **use** | none | Public board APIs, ~7.5k mapped companies. `list_open_jobs`, `compare_companies`. No scraping, no key |
| Greenhouse Harvest | [mikelane/greenhouse-mcp-server](https://github.com/mikelane/greenhouse-mcp-server) | | | | | y | **reject** for applicants | Harvest API token | Recruiter-side. Not for Job Apply OS applicants |
| RemoteOK | HTTP `https://remoteok.com/api` | y | | | | | **use** | none | First JSON element is metadata — skip it |
| Hiring Cafe | `scripts/fetch_hiringcafe.py` | y | | | | | **use** | none | Public `__NEXT_DATA__`. Store employer apply URL |
| Weekday | none found | y | | | | | **gap** | | Public pages / Workable |
| Roro Remote | none found | | | | | | **gap** | | Confirm live URL on first discovery cycle |
| Flexiple / Turing / Toptal / Lemon.io / BairesDev | none found | | | | y | y | **gap** | profile | `apply_kind: network`. Playwright for intake forms (apply role) |
| Amazon / MSFT / Google / Uber careers | Playwright + dorks | y | | | | y | **use** | account on apply | See `big-tech-careers.md` |
| Gmail | Cursor Gmail MCP (this agent) | | | y | y | | **use** | OAuth already | `create_draft` **must** include PDF attachment. `send_message` only after human/policy allows |
| Gmail | Official `https://gmailmcp.googleapis.com/mcp/v1` | | | y | y | | **use** alt | Google Cloud OAuth client | For clients that are not Cursor Cloud |
| Gmail skills.sh | `googleworkspace/cli@gws-gmail*` | | | y | | | **fork** | gws CLI | Fallback if MCP is down; not a second mailer |
| Google Drive | Cursor Drive MCP (this agent) | | y | | | | **use** | OAuth already | Mirror of ledger PDFs only. Git is source of truth |
| Google Calendar | Cursor Calendar MCP (this agent) | | | | y | | **use** | OAuth already | `suggest_time` / `create_event` after a real interview ask |
| Google People | `https://people.googleapis.com/mcp/v1` | | y | | | | **fork** | Workspace OAuth | Contacts you already have — not a hunter |
| Hunter | Official `https://mcp.hunter.io/mcp` | | y | | y | | **use** | API key header | Find + verify emails. Do not send on unverified |
| Apollo | Official `https://mcp.apollo.io/mcp` | y | y | y | y | | **fork** | OAuth | People search + enrichment + sequences. Sequences are a spray tool — **off** unless the user adds them. People/enrichment OK |
| Smartlead / Instantly MCPs | community cold-email servers | | | y | y | | **reject** default | API key | High-volume sequences. Violates “not a spray” and the 2-touch cap. Revisit only if the user adds that channel |
| Playwright | `@playwright/mcp` | | | | y | y | **use** | none | Apply + LinkedIn DM bots. Headless in cloud VMs |
| Exa | remote MCP | y | y | | | | **use** | OAuth / `EXA_API_KEY` | Default research |
| Firecrawl | `firecrawl-mcp` | | y | | | | **use** | `FIRECRAWL_API_KEY` | URL extract; also powers local deep-research |
| Tavily | tavily-mcp | | y | | | | **use** | `TAVILY_API_KEY` | Fast confirmation search |
| Parallel Search | official `https://search.parallel.ai/mcp` | | y | | | | **use** | none on free tier | Maintainer pass 2026-09-06. Added to `mcp.example.json`. Bearer key for production |
| dzhng/deep-research | local CLI/API | | y | | | | **use** | Firecrawl + OpenAI | Wired in `.cursor/environment.json`. See deep-research catalog |
| jobpilot-mcp | RemoteOK + WWR + Himalayas + auto_apply | y | | | | y | **reject** as discovery | Notion + Playwright | Combined search-and-apply. May fork `search_jobs` later |
| jobhound | Ashby/Greenhouse/Lever + apply | y | | | | y | **reject** as discovery | | Same split problem |
| Apify Wellfound/Indeed actors | hosted scrape | y | | | | | **reject** default | Apify OAuth | ToS / scrape farm. Prefer official APIs |
| compose-outreach / draft-outreach (Anthropic knowledge-work-plugins) | copy skill | | | | y | | **fork** | Common Room MCP | Good writing bar; depends on Common Room. Do not send from the skill |

## Known skill families to evaluate (not auto-installed)

When you vet one, append a `### <name>` block. 2026-09-06 verdicts:

### stickerdaniel/linkedin-mcp-server
- source: https://github.com/stickerdaniel/linkedin-mcp-server
- capability: jobs, people, company, messages via a logged-in browser
- role: discovery (search tools only) | outreach (DM tools, separate bot)
- verdict: fork
- notes: Enable `search_jobs` / `get_job_details` / `search_people` after the human confirms they own the LinkedIn session. Do not enable messaging on the discovery environment.

### firecrawl-deep-research
- source: `npx skills add https://github.com/firecrawl/firecrawl-workflows --skill firecrawl-deep-research` (33.7k installs on skills.sh)
- capability: report-scale cited web research
- role: research
- verdict: fork
- notes: Skill itself says skip it for quick lookups. Job Apply OS briefs are short. Prefer Exa or the local dzhng runner with depth 2.

### proficientlyjobs@job-search / daangn-jobs-search / boss-job-search
- source: skills.sh `npx skills find "job search"`
- capability: regional boards (Korea, etc.)
- role: discovery
- verdict: reject unless the candidate's locations include those markets
- notes: Not in `platforms.md`. Add a platform row first if the human wants them.

### anthropics/knowledge-work-plugins@compose-outreach
- source: https://skills.sh/anthropics/knowledge-work-plugins/compose-outreach
- capability: email + LinkedIn message drafts from Common Room signals
- role: outreach
- verdict: fork
- notes: Copy quality is in scope. Sending is Gmail MCP. Common Room is extra auth.

### paramchoudhary/resumeskills@linkedin-profile-optimizer
- source: skills.sh
- capability: resume / LinkedIn profile rewrite
- role: apply
- verdict: reject
- notes: User does not want resume curation.

### gooseworks-ai end-to-end-hiring-signal
- source: skills.sh
- capability: company list → job signals → outreach campaign
- role: n/a
- verdict: reject
- notes: Sales hiring-signal spray. Combined pipeline with no discovery stop flag.

## Workspace log

| date | actor | queried | added | rejected |
| --- | --- | --- | --- | --- |
| 2026-09-06 | template | skills.sh, skills-hub.ai, GitHub, Indeed docs, Exa docs | Exa deep research, Indeed MCP, workatastartup-mcp, RemoteOK API, Gmail attachments | combined auto-apply as discovery |
| 2026-09-06 | cursor-cloud-agent | skills.sh, skills-hub CLI, GitHub, PyPI, Indeed/Exa/Firecrawl/Tavily/Hunter/Apollo/Google Workspace docs, dzhng/deep-research clone | dzhng/open-deep-research local runner + cloud `environment.json`; ats-jobs-mcp; Hunter MCP; Playwright MCP; Google Calendar/Drive (already attached); platform MCP matrix | LinkedIn cookie messengers as discovery; Smartlead/Instantly sequences; Greenhouse Harvest recruiter MCP; resume-optimizer skills; jobpilot/jobhound combined apply; Apify scrapers as default |
| 2026-09-06 | cursor-cloud-agent (maintainer) | npx skills add + hiringcafe.com public pages | Pinned uvx MCPs (no source trees); agent skills compose/draft-outreach + playwright-cli; Hiring Cafe platform + fetch_hiringcafe.py; mcp/hosted copy-paste configs | Apify HiringCafe scrapers; LinkedIn session MCPs not vendored; ats-jobs directory.json stays in the PyPI wheel |
| 2026-09-15 | cursor-cloud-agent (maintainer) | Hub registry + memory solidify e2e (no new marketplace search) | In-process e2e for tagged skills, memory solidify, maintainer proctor/promote; catalog date refreshed so discovery.search is unblocked | no new rejections |

## Indeed MCP notes

Official docs: https://docs.indeed.com/mcp/

- Remote MCP, Streamable HTTP, OAuth with an Indeed account
- Endpoint advertised for Claude: `https://mcp.indeed.com/claude/mcp`
- Tools: Job Search, Job Detail, Get Resume, Get Company Data
- Availability can be connector-limited (historically Claude connector). If Cursor cannot attach it, discovery uses public Indeed URLs + dorks and writes that limitation here.
- **This cloud agent (2026-09-06):** Indeed MCP is **not** in the attached namespace list. Treat as unavailable until a human adds the connector.

## Gmail PDF attachments

Outreach has been failing this in the wild when the agent sends `body` only.

Correct draft shape (this agent's `Gmail.create_draft`):

- `to` (array of addresses), `subject`, `body` and/or `htmlBody`
- `attachments`: `{ filename: "Ada-Example-Resume.pdf", mimeType: "application/pdf", content: "<base64>" }`
- Combined attachments ≤ 25MB. Resume PDFs are fine. If larger, upload to Drive and put the link in the body **in addition to** still attaching a normal-size PDF when possible.

Read the PDF from `assets/resume/`, base64 it, then create the draft. If the tool errors, stop and mark the touch `blocked: attachment`. Do not send without the file.

`send_message` exists on this agent. Default: **draft**, then send only when the outreach skill says to and the PDF is on the draft.

## Google Drive + Calendar notes

Drive: optional overlay. Folder id in `.env` as `GOOGLE_DRIVE_LEDGER_FOLDER_ID`. Write git first.

Calendar: after status `interview` (or when a recruiter proposes times). Use `suggest_time` across calendars. Do not silently create events on the candidate's calendar without the human's ask.

## Hunt board (maintainer-owned adopted infra)

First-party live coordination plane: [`docs/job-hub/human.md`](../../docs/job-hub/human.md). FastAPI + SQLite + admin UI. **Maintainer owns it** (tokens, uptime, schema, hygiene, tunnels, skill registry + proctor). Discovery/apply/outreach consume tagged registry skills; they do not promote shared rows.

Not a marketplace MCP. Do not confuse with rejected `job-tracker-sqlite` (third-party MCP). Git `ledger/` remains the airgap protocol.

Install: `bash scripts/hub_start.sh`. Tokens: `uv run scripts/board_gen_tokens.py --print` (gitignored).

## Hunter / Apollo notes

- Hunter: verify before any email send. Confidence scores go on `ledger/people/<id>.yaml`. Low confidence → LinkedIn DM only.
- Apollo sequences and Smartlead/Instantly: off by default. AGENTS.md channels are email + LinkedIn DMs with `max_outreach_touches_per_person`.
