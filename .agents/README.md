# Downloaded Agent Skills

Canonical third-party skills installed with `npx skills add` (see `skills-lock.json`).

OS skills stay in `/skills`. Do not copy these into `/skills` under the same names.

Refresh:

```bash
bash scripts/install_agent_skills.sh
```

| Skill | Source | Role |
| --- | --- | --- |
| compose-outreach | anthropics/knowledge-work-plugins | Outreach copy. Common Room MCP optional; if missing, skip CR tools and use ledger + deep-research. **Do not send from this skill** — Gmail MCP with PDF. |
| draft-outreach | anthropics/knowledge-work-plugins | Outreach copy via web research. Same send rule. |
| playwright-cli | microsoft/playwright-cli | Apply bot only. Never on discovery. |

Claude Code and Cursor see them through per-skill symlinks in `.claude/skills/` and `.cursor/skills/` (`bash scripts/link_agent_skills.sh`).
