# Skills

Agent Skills for this template. Canonical files live in `skills/<name>/SKILL.md`.

Cursor picks them up from `skills/`. Claude Code / Claude agents pick them up from `.claude/skills`, which is a symlink to this directory. Do not duplicate skill folders.

Alternatively copy a skill into `~/.cursor/skills/` or `~/.claude/skills/` for user-global install.

| Skill | Role |
| --- | --- |
| [skill-and-mcp-catalog](skill-and-mcp-catalog/SKILL.md) | Procurement: find and vet skills/MCPs from any registry |
| [skill-maintainer](skill-maintainer/SKILL.md) | Seldom-used owner: write `skills/lists/`, prune, patch example MCP config |
| [deep-research](deep-research/SKILL.md) | Shared research via Exa (preferred), local dzhng/open-deep-research, or Firecrawl/Tavily/Parallel/search |
| [job-discovery](job-discovery/SKILL.md) | Source and shortlist only |
| [job-apply](job-apply/SKILL.md) | Submit with writing worth reading |
| [job-outreach](job-outreach/SKILL.md) | Email + LinkedIn DM, PDF on email |

The three job owners are discovery, apply, outreach. Catalog and deep research are capabilities those owners call. Maintainer is a fourth owner and is seldom used. Human board for tools: [`lists/INDEX.md`](lists/INDEX.md).
