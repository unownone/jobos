---
name: skill-and-mcp-catalog
description: Discover, vet, and add agent skills and MCP servers from any registry (skills.sh, Skills Hub, ClawHub, GitHub, mcp.so, vendor docs). Use when setting up Job Apply OS, when a portal has no tool, or when the user mentions Skillhub, skills.sh, MCP install, Indeed MCP, Exa, or missing capabilities. Do not lock to one marketplace.
---

# Skill and MCP catalog

You are the procurement desk for this workspace. Find tools, vet them, write them down. Do not run job applications.

## When

- First discovery cycle in a new clone
- A platform in `docs/catalogs/platforms.md` has no method
- An MCP auth failed
- User asks to “look up skills / MCPs”

## Do

1. Read `docs/catalogs/skills-and-mcps.md` and `skills/lists/INDEX.md`. Skip registries already queried this week unless the user wants a refresh.
2. Search **at least two** of: `npx skills find`, Skills Hub CLI, GitHub `path:SKILL.md`, mcp.so / Smithery, official vendor docs.
3. Prefer capabilities this repo already named: LinkedIn job **discovery** (not apply), LinkedIn / ATS apply (apply role only), Indeed MCP, Work at a Startup MCP, Wellfound search, RemoteOK, Exa/Firecrawl/Tavily/Parallel deep research, Gmail with attachments, Drive.
4. Vet with the rubric in the catalog doc.
5. Append the workspace log and any new rows. Maintainer also writes `skills/lists/`.
6. If installing, install into the **correct role’s** environment. Never enable auto-apply on a discovery bot.
7. Tell the human what needs OAuth (Indeed, Exa, Gmail, Drive) — do not pretend it is connected.

## Do not

- Install a combined search-and-spray skill as the discovery workflow
- Put API keys in the catalog doc
- Treat a marketing page as a working MCP

## Output

A short table: capability, chosen tool, install line, role, leftover gaps.

If you were invoked as **maintainer**, also write `skills/lists/` and run `uv run scripts/rebuild_skill_index.py`.

Then stop, unless you were called as a prelude to `job-discovery`.
