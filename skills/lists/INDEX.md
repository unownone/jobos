# Skill and MCP lists

Machine-readable source: `adopted.yaml`, `wanted.yaml`, `rejected.yaml`, `by-platform.yaml`, `sources.yaml`.

Rebuild: `uv run scripts/rebuild_skill_index.py`.

**Last maintainer pass:** 2026-09-06 by `cursor-cloud-agent`.

Owner: [`skills/skill-maintainer/SKILL.md`](../skill-maintainer/SKILL.md) (seldom). Discovery still runs the catalog skill at the start of a cycle; this folder is what the maintainer writes.

Narrative inventory: [`docs/catalogs/skills-and-mcps.md`](../../docs/catalogs/skills-and-mcps.md).

## Registries this pass

- **skills.sh** (`npx skills find`)
- **skills-hub.ai** (`npx @skills-hub-ai/cli search`)
- **github** (`web + vendor README`)
- **vendor-docs** (`WebFetch / WebSearch`)
- **smithery-glama** (`WebSearch`)

## Adopted

| id | name | kind | capability | roles | verdict | install |
| --- | --- | --- | --- | --- | --- | --- |
| `skill-and-mcp-catalog` | skill-and-mcp-catalog | skill | maintain, discovery | discovery, maintainer | use | in-repo |
| `skill-maintainer` | skill-maintainer | skill | maintain | maintainer | use | in-repo |
| `job-discovery` | job-discovery | skill | discovery | discovery | use | in-repo |
| `job-apply` | job-apply | skill | apply | apply | use | in-repo |
| `job-outreach` | job-outreach | skill | outreach, mail | outreach | use | in-repo |
| `deep-research` | deep-research | skill | research | all | use | in-repo |
| `exa-mcp` | Exa MCP | mcp | research, discovery | all | use | https://mcp.exa.ai/mcp?tools=web_search_exa,web_search_advanced_exa,company_research_exa,linkedin_search_exa,deep_researcher_start,deep_researcher_check,agent_run,crawling_exa |
| `dzhng-open-deep-research` | dzhng/deep-research (open-deep-research) | local | research | all | use | bash scripts/setup_deep_research.sh then python3 scripts/run_deep_research.py |
| `firecrawl-mcp` | Firecrawl MCP | mcp | research | discovery, maintainer | use | npx -y firecrawl-mcp |
| `tavily-mcp` | Tavily MCP | mcp | research | all | use | npx -y tavily-mcp@latest or https://mcp.tavily.com/mcp/?tavilyApiKey= |
| `parallel-search-mcp` | Parallel Search MCP | mcp | research | all | use | https://search.parallel.ai/mcp |
| `indeed-mcp` | Official Indeed MCP | mcp | discovery, research | discovery | use | https://mcp.indeed.com/claude/mcp |
| `workatastartup-mcp` | workatastartup-mcp | mcp | discovery, research | discovery | use | bash scripts/mcp/workatastartup.sh (vendored in vendor/mcp/workatastartup-mcp) |
| `ats-jobs-mcp` | ats-jobs-mcp | mcp | discovery | discovery | use | bash scripts/mcp/ats-jobs.sh (vendored in vendor/mcp/ats-jobs-mcp) |
| `job-scout-mcp` | job-scout-mcp | mcp | discovery | discovery | use | bash scripts/mcp/job-scout.sh (vendored; dist committed) |
| `hiringcafe-http` | Hiring Cafe public pages | http | discovery | discovery | use | python3 scripts/fetch_hiringcafe.py --query "staff software engineer" |
| `compose-outreach` | anthropics compose-outreach | skill | outreach | outreach | use | bash scripts/install_agent_skills.sh |
| `draft-outreach` | anthropics draft-outreach | skill | outreach | outreach | use | bash scripts/install_agent_skills.sh |
| `playwright-cli-skill` | microsoft/playwright-cli | skill | apply | apply | use | bash scripts/install_agent_skills.sh |
| `remoteok-http` | RemoteOK public API | http | discovery | discovery | use | GET https://remoteok.com/api |
| `websearch-dorks` | WebSearch + ATS dorks | builtin | discovery | discovery | use | built-in WebSearch / Exa advanced |
| `gmail-mcp` | Gmail MCP | mcp | mail, outreach | outreach | use | Cursor-hosted Gmail namespace, or https://gmailmcp.googleapis.com/mcp/v1 |
| `google-drive-mcp` | Google Drive MCP | mcp | research | discovery, outreach | use | Cursor-hosted Drive, or https://drivemcp.googleapis.com/mcp/v1 |
| `google-calendar-mcp` | Google Calendar MCP | mcp | outreach | outreach | use | Cursor-hosted Calendar, or https://calendarmcp.googleapis.com/mcp/v1 |
| `hunter-mcp` | Hunter MCP | mcp | research, outreach | outreach | use | https://mcp.hunter.io/mcp with X-API-Key |
| `playwright-mcp` | Playwright MCP | mcp | apply, outreach | apply, outreach | use | npx @playwright/mcp@latest |
| `cursor-gmail-this-agent` | Cursor Gmail (this cloud agent) | mcp | mail, outreach | outreach | use | already attached |

## Wanted (next attach / fork / gap)

| id | name | kind | capability | roles | verdict | next_action |
| --- | --- | --- | --- | --- | --- | --- |
| `linkedin-mcp-stickerdaniel` | stickerdaniel/linkedin-mcp-server | mcp | discovery, research | discovery | fork | Only after the human says they own a LinkedIn session. Disable send_message on discovery. |
| `hs-linkedin-resolve` | hs-linkedin-mcp (resolve_apply_url only) | mcp | apply, discovery | apply | fork | Apply-role only. Use resolve_apply_url so packets store the real ATS URL. Do not enable Easy Apply drive-to-completion on discovery. |
| `apollo-people` | Apollo MCP (people + enrichment only) | mcp | research, outreach | outreach | fork | Attach on outreach env. Deny-list sequence tools. People search OK. |
| `brave-search-mcp` | Brave Search MCP | mcp | research | all | fork | Only if Exa + Tavily + Parallel are all missing. Needs BRAVE_API_KEY. |
| `gws-gmail-cli` | googleworkspace/cli gws-gmail | cli | mail | outreach | fork | Fallback if Gmail MCP dies. Not a second mailer. |
| `firecrawl-deep-research-skill` | firecrawl/firecrawl-workflows@firecrawl-deep-research | skill | research | all | fork | Only when the human wants a long cited report. Default brief stays Exa / dzhng depth 2. |
| `parallel-deep-research-skill` | parallel-web/parallel-agent-skills@parallel-deep-research | skill | research | all | fork | Optional long-report path using Parallel. Default still Exa. Search MCP already adopted. |
| `weekday-method` | Weekday public pages | gap | discovery | discovery | gap | First discovery cycle records whether listings are Workable. No MCP found on skills.sh / GitHub this pass. |
| `rororemote-method` | Roro Remote | gap | discovery | discovery | gap | First discovery actor searches the live URL, then platforms.md or outreach_only. |
| `wellfound-method` | Wellfound public site | gap | discovery | discovery | gap | No official MCP. Do not add Apify/Wellfound scrapers unless the user accepts ToS risk in writing. |
| `network-playwright` | Talent-network intake (Playwright) | gap | apply, outreach | apply | gap | One job file per network, apply_kind network. No MCP exists; do not invent one. |

## Rejected

| id | name | kind | capability | roles | reason | source |
| --- | --- | --- | --- | --- | --- | --- |
| `resume-linkedin-optimizer` | paramchoudhary/resumeskills@linkedin-profile-optimizer | skill | apply | User does not want resume or LinkedIn-profile curation. | User does not want resume or LinkedIn-profile curation. | https://skills.sh |
| `linkedin-ghostwriting` | linkedin-posts / linkedin-ghostwriting | skill | outreach | Content mill, not application outreach (email + LinkedIn DM). | Content mill, not application outreach (email + LinkedIn DM). | skills.sh |
| `cold-email-writer` | paramchoudhary/resumeskills@cold-email-writer | skill | outreach | 4.1K installs but generic spray copy. Outreach uses in-repo templates + proof from the profile. | 4.1K installs but generic spray copy. Outreach uses in-repo templates + proof from the profile. | https://skills.sh/paramchoudhary/resumeskills/cold-email-writer |
| `smartlead-instantly` | Smartlead / Instantly sequence MCPs | mcp | mail, outreach | High-volume sequences. Violates 2-touch cap and “not a spray.” | High-volume sequences. Violates 2-touch cap and “not a spray.” | community |
| `apollo-sequences` | Apollo sequence tools | mcp | outreach | People/enrichment may be forked. Sequence tools stay off. | People/enrichment may be forked. Sequence tools stay off. | https://docs.apollo.io/docs/apollo-mcp |
| `gooseworks-hiring-signal` | gooseworks-ai end-to-end-hiring-signal | skill | discovery, outreach | Combined pipeline with no discovery stop flag. Sales spray. | Combined pipeline with no discovery stop flag. Sales spray. | skills.sh |
| `gooseworks-job-scraper` | gooseworks-ai/goose-skills@job-scraper / linkedin-job-scraper | skill | discovery | Scraper family. Prefer official APIs / public ATS JSON. | Scraper family. Prefer official APIs / public ATS JSON. | https://skills.sh/gooseworks-ai/goose-skills/job-scraper |
| `jobpilot-mcp` | jobpilot-mcp | mcp | discovery, apply | Combined search-and-apply. May fork search_jobs later; not discovery default. | Combined search-and-apply. May fork search_jobs later; not discovery default. | community |
| `jobhound` | jobhound | mcp | discovery, apply | Same split problem as jobpilot. | Same split problem as jobpilot. | community |
| `go-job` | anatolykoptev/go-job | mcp | discovery, apply | Maintainer pass 2026-09-06. 28 tools including opportunity_claim and LinkedIn easy_apply filter. Combined search-and-act. Reject as discovery.  | Maintainer pass 2026-09-06. 28 tools including opportunity_claim and LinkedIn easy_apply filter. Combined search-and-act. Reject as discovery.  | https://github.com/anatolykoptev/go-job |
| `jobspy-mcp` | VennieSo/jobspy-mcp-server | mcp | discovery | python-jobspy scrape of LinkedIn/Indeed/Glassdoor. Not an official API. | python-jobspy scrape of LinkedIn/Indeed/Glassdoor. Not an official API. | https://github.com/VennieSo/jobspy-mcp-server |
| `jobspipe-mcp` | jobspipe/jobspipe-mcp | mcp | discovery | Hosted aggregator including LinkedIn scrape + Upwork. Prefer ats-jobs-mcp + public feeds. | Hosted aggregator including LinkedIn scrape + Upwork. Prefer ats-jobs-mcp + public feeds. | https://smithery.ai/servers/jobspipe/jobspipe-mcp |
| `prakharagarwal-linkedin-mcp` | prakharagarwal-dev/linkedin-mcp-server | mcp | discovery, outreach, apply | Combines search, publish, and messaging. Do not enable as-is on discovery. | Combines search, publish, and messaging. Do not enable as-is on discovery. | GitHub |
| `greenhouse-harvest` | mikelane/greenhouse-mcp-server / membranedev greenhouse-harvest | mcp | apply | Recruiter-side Harvest API. Not for applicants. | Recruiter-side Harvest API. Not for applicants. | https://skills.sh/membranedev/application-skills/greenhouse-harvest |
| `waas-cookie-fork` | moutasem-isentemiz/workatastartup-mcp | mcp | discovery | Cookie-session fork. Prefer PyPI public workatastartup-mcp. | Cookie-session fork. Prefer PyPI public workatastartup-mcp. | GitHub |
| `apify-scrapers` | Apify Wellfound/Indeed actors | mcp | discovery | ToS / scrape farm. Prefer official APIs. | ToS / scrape farm. Prefer official APIs. | Apify |
| `antibrow-browser` | antibrow/anti-detect-browser-skills@browser-mcp-agent | skill | apply | 44.6K installs but anti-detect browser. Use official Playwright MCP. | 44.6K installs but anti-detect browser. Use official Playwright MCP. | https://skills.sh/antibrow/anti-detect-browser-skills/browser-mcp-agent |
| `wellfound-lead-scraper` | sam6dvpte34/lead-generation-skill@wellfound-startup-lead-scraper | skill | discovery | Lead-gen scraper, not a job board API. | Lead-gen scraper, not a job board API. | skills.sh |
| `indeed-lead-scraper` | sam6dvpte34/lead-generation-skill@indeed-job-lead-scraper | skill | discovery | Lead-gen scraper. Prefer official Indeed MCP. | Lead-gen scraper. Prefer official Indeed MCP. | skills.sh |
| `regional-job-boards` | daangn-jobs-search / jobkorea / boss-job-search / proficientlyjobs | skill | discovery | Regional boards (Korea etc.) not in platforms.md. Add a platform row first if the human wants them. | Regional boards (Korea etc.) not in platforms.md. Add a platform row first if the human wants them. | skills.sh |
| `theirstack` | TheirStack jobs MCP | mcp | discovery | Paid aggregator. Template prefers public ATS JSON + official Indeed. Revisit only if the human pays. | Paid aggregator. Template prefers public ATS JSON + official Indeed. Revisit only if the human pays. | https://theirstack.com/en/blog/best-jobs-mcp |
| `job-tracker-sqlite` | kurkul608/job-tracker-mcp | mcp | maintain | Parallel ledger in SQLite. Git YAML is the live list. | Parallel ledger in SQLite. Git YAML is the live list. | https://github.com/kurkul608/job-tracker-mcp |
| `skills-hub-false-positives` | azure-microsoft-discovery / customer-discovery | skill | discovery | Name collision. Not job-board discovery. | Name collision. Not job-board discovery. | npx @skills-hub-ai/cli search "job discovery" |
| `contact-hunter-skill` | onewave-ai/claude-skills@contact-hunter | skill | outreach | Not Hunter.io. Use official Hunter MCP for verify-before-send. | Not Hunter.io. Use official Hunter MCP for verify-before-send. | skills.sh |

## Platform map

See [`by-platform.yaml`](by-platform.yaml) for `docs/catalogs/platforms.md` ids → list ids.
