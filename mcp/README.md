# MCP config

Copy [`mcp.example.json`](mcp.example.json) into your client's MCP file (`~/.cursor/mcp.json` or project `.cursor/mcp.json`), then copy to gitignored `mcp/mcp.local.json` if you keep secrets beside the repo.

This template does **not** vendor a hosted stack. Attach what the current role needs.

## Discovery (do not put Playwright or send-mail here)

1. **Exa** — deep research (strongly recommended)
2. **Firecrawl / Tavily** — fallbacks
3. **Indeed** — official OAuth MCP if your client can add the Indeed connector (`https://mcp.indeed.com/claude/mcp`, historically Claude)
4. **workatastartup-mcp** — YC jobs (`uvx workatastartup-mcp`)
5. **ats-jobs-mcp** — Greenhouse / Ashby / Lever public boards (`uvx ats-jobs-mcp`)

Local recursive research is **not** an MCP: `.cursor/environment.json` clones [dzhng/deep-research](https://github.com/dzhng/deep-research) and operators run `python3 scripts/run_deep_research.py`. See [`docs/catalogs/deep-research.md`](../docs/catalogs/deep-research.md).

## Outreach

1. **Gmail** — drafts with PDF attachments. Cursor Cloud may already attach a Gmail MCP; otherwise Google remote `https://gmailmcp.googleapis.com/mcp/v1`
2. **Google Drive** — optional ledger overlay
3. **Google Calendar** — interview times after a real reply
4. **Hunter** — verify emails (`https://mcp.hunter.io/mcp`, `X-API-Key`)
5. **Apollo** — optional people/enrichment. Do not enable sequence tools unless the user adds that channel

## Apply only

1. **Playwright MCP** — `npx @playwright/mcp@latest` for ATS and LinkedIn Easy Apply after a packet exists

Auth stays on the machine that owns the portal (usually discovery for Indeed/Exa, outreach for Gmail). Airgapped apply bots do not need those keys.

Indeed notes: https://docs.indeed.com/mcp/
Exa notes: https://github.com/exa-labs/exa-mcp-server
Google Workspace MCP: https://developers.google.com/workspace/guides/configure-mcp-servers
Hunter MCP: https://hunter.io/mcp
Apollo MCP: https://docs.apollo.io/docs/apollo-mcp

Full inventory: [`docs/catalogs/skills-and-mcps.md`](../docs/catalogs/skills-and-mcps.md).
