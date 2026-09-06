# Skills

Agent Skills for this template.

- **OS skills** (this folder): Cursor loads `skills/<name>/SKILL.md`.
- **Third-party skills**: `.agents/skills/` via `npx skills add` (`skills-lock.json`). Refresh: `bash scripts/install_agent_skills.sh`.
- **Claude Code + Cursor links**: `.claude/skills/<name>` and `.cursor/skills/<name>` are **per-skill** symlinks (`bash scripts/link_agent_skills.sh`). A single directory symlink is not enough for some Claude clients.

| Skill | Role |
| --- | --- |
| [skill-and-mcp-catalog](skill-and-mcp-catalog/SKILL.md) | Procurement: find and vet skills/MCPs from any registry |
| [skill-maintainer](skill-maintainer/SKILL.md) | Seldom-used owner: write `skills/lists/`, prune, patch example MCP config |
| [deep-research](deep-research/SKILL.md) | Shared research via Exa (preferred), local dzhng/open-deep-research, or Firecrawl/Tavily/Parallel/search |
| [job-discovery](job-discovery/SKILL.md) | Source and shortlist only |
| [job-apply](job-apply/SKILL.md) | Submit with writing worth reading |
| [job-outreach](job-outreach/SKILL.md) | Email + LinkedIn DM, PDF on email |
| [playwright-cli](../.agents/skills/playwright-cli/SKILL.md) | Apply: browser CLI (vendored agent skill) |
| [draft-outreach](../.agents/skills/draft-outreach/SKILL.md) | Outreach copy helper (vendored; do not send) |
| [compose-outreach](../.agents/skills/compose-outreach/SKILL.md) | Outreach copy helper (vendored; Common Room optional) |

The three job owners are discovery, apply, outreach. Catalog and deep research are capabilities those owners call. Maintainer is a fourth owner and is seldom used. Human board for tools: [`lists/INDEX.md`](lists/INDEX.md).
