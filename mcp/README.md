# MCP config

Copy [`mcp.example.json`](mcp.example.json) into your client's MCP file (`~/.cursor/mcp.json` or project `.cursor/mcp.json`).

This template does **not** vendor a hosted stack. Attach:

1. **Exa** — deep research (strongly recommended)
2. **Indeed** — official OAuth MCP if your client can add the Indeed connector
3. **Gmail** — outreach drafts with attachments
4. **Google Drive** — optional
5. **Firecrawl / Tavily** — fallbacks
6. **workatastartup-mcp** — if you use YC jobs heavily

Auth stays on the machine that owns the portal (usually discovery for Indeed/Exa, outreach for Gmail). Airgapped apply bots do not need those keys.

Indeed notes: https://docs.indeed.com/mcp/
Exa notes: https://github.com/exa-labs/exa-mcp-server
