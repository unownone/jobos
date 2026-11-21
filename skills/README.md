# Skills

Agent Skills for this template.

- **OS skills** (this folder): Cursor loads `skills/<name>/SKILL.md`.
- **Starter tagged skills**: [`starters/`](starters/) YAML seeded into the Hub registry on boot.
- **Live registry**: Hub `GET /api/registry/skills` (shared approved + own local). Outline: [`docs/catalogs/skill-outline.md`](../docs/catalogs/skill-outline.md).
- **Third-party skills**: `.agents/skills/` via `npx skills add` (`skills-lock.json`). Refresh: `bash scripts/install_agent_skills.sh`.
- **Claude Code + Cursor links**: `.claude/skills/<name>` and `.cursor/skills/<name>` are **per-skill** symlinks (`bash scripts/link_agent_skills.sh`). A single directory symlink is not enough for some Claude clients.

| Skill | Role | Tags |
| --- | --- | --- |
| [skill-and-mcp-catalog](skill-and-mcp-catalog/SKILL.md) | maintain | maintain, source |
| [skill-maintainer](skill-maintainer/SKILL.md) | maintain | maintain |
| [deep-research](deep-research/SKILL.md) | research | research |
| [job-discovery](job-discovery/SKILL.md) | discovery | source |
| [job-apply](job-apply/SKILL.md) | apply | apply |
| [job-outreach](job-outreach/SKILL.md) | outreach | outreach |
| [playwright-cli](../.agents/skills/playwright-cli/SKILL.md) | apply | apply |
| [draft-outreach](../.agents/skills/draft-outreach/SKILL.md) | outreach | outreach |
| [compose-outreach](../.agents/skills/compose-outreach/SKILL.md) | outreach | outreach |

The three job owners are discovery, apply, outreach. Catalog and deep research are capabilities those owners call. Maintainer is a fourth owner and is seldom used: it writes `skills/lists/`, owns the Hub, seeds GitHub starters into the registry, and is the **only consumer** of `skill.record`. Human board for tools: [`lists/INDEX.md`](lists/INDEX.md). Tagged platform playbooks: [`starters/README.md`](starters/README.md).
