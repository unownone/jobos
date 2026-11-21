# MCP setup (copy-paste)

Goal: attach tools so discovery / apply / outreach can run **from a fresh clone** without guessing URLs.

1. Copy [`mcp.example.json`](mcp.example.json) into the client file:
   - Cursor: project `.cursor/mcp.json` or `~/.cursor/mcp.json`
   - Claude Code: `.mcp.json` or Claude Desktop `claude_desktop_config.json`
2. Keep secrets in gitignored `mcp/mcp.local.json` or `.env` — never in git.
3. Local servers use `bash scripts/mcp/*.sh` (`uvx` pins for Python; job-scout clones into gitignored `agent-tools/`).
4. Hosted servers: copy a snippet from [`hosted/`](hosted/) (one file per server) if you only want that tool.

Cloud-agent install warms the uvx cache and job-scout clone via `scripts/setup_vendor_mcps.sh`.

## What is already wired (local)

| Server | Command (from repo root) | Auth |
| --- | --- | --- |
| Work at a Startup | `bash scripts/mcp/workatastartup.sh` | none |
| ATS boards (Greenhouse / Ashby / Lever) | `bash scripts/mcp/ats-jobs.sh` | none |
| job-scout (ATS + HN + RemoteOK) | `bash scripts/mcp/job-scout.sh` | none (optional Adzuna/USAJobs env) |
| Hiring Cafe | not an MCP — public hiringcafe.com `/jobs/...` pages | none |

First Python MCP launch needs network once (`uvx` downloads the pinned wheel). The ATS company directory is inside that wheel, not this repo.

## What you attach (hosted)

| Server | Snippet | Auth |
| --- | --- | --- |
| Exa | [`hosted/exa.json`](hosted/exa.json) | OAuth or `EXA_API_KEY` |
| Parallel Search | [`hosted/parallel-search.json`](hosted/parallel-search.json) | none on free tier |
| Firecrawl | [`hosted/firecrawl.json`](hosted/firecrawl.json) | `FIRECRAWL_API_KEY` |
| Tavily | [`hosted/tavily.json`](hosted/tavily.json) | `TAVILY_API_KEY` |
| Indeed | [`hosted/indeed.json`](hosted/indeed.json) | Indeed OAuth; often Claude Connector only |
| Hunter | [`hosted/hunter.json`](hosted/hunter.json) | `HUNTER_API_KEY` header |
| Apollo | [`hosted/apollo.json`](hosted/apollo.json) | OAuth; people/enrichment only |
| Gmail / Drive / Calendar | [`hosted/google-workspace.json`](hosted/google-workspace.json) | Google OAuth |
| Playwright (apply bot) | [`hosted/playwright.json`](hosted/playwright.json) | none |

Cursor Cloud on this project may already attach Gmail, Drive, and Calendar. Do not run two Gmail servers at once.

## Role split

- **Discovery:** Exa or Parallel, workatastartup, ats-jobs, job-scout. No Playwright, no Gmail send.
- **Apply:** Playwright only after a packet exists.
- **Outreach:** Gmail (PDF attachment required), Hunter, Calendar.

## Claude Desktop merge

Claude Desktop wants a single `mcpServers` object. Merge local keys from `mcp.example.json` with the hosted files you need. Relative `bash scripts/mcp/...` works if Desktop’s cwd is the repo; otherwise replace with absolute paths to those scripts.
