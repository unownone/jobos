# Contributing to the template

This repo is the **operating system**, not a live job search. Keep PII and live ledgers out of public history.

## Change the process, then the skills

1. Edit `docs/process.md` (contract)
2. Align `docs/architecture.md` / `docs/roles.md` / `docs/sharing.md` if the motion changed
3. Update the matching `skills/*/SKILL.md` (Claude agents see the same files via `.claude/skills` → `../skills`)
4. If you added or dropped a tool, update `skills/lists/` and run `uv run scripts/rebuild_skill_index.py`
5. Update catalogs if portals or MCPs changed

Skills should stay short and point at docs. Do not fork the status enum in three places — `ledger/schema/job.schema.json` is the list.

## Add a platform

Add a row to `docs/catalogs/platforms.md` or `big-tech-careers.md`. If it needs a tool, run the catalog skill (or the **maintainer** skill if you are updating lists) and log it in `docs/catalogs/skills-and-mcps.md` plus `skills/lists/`. Coverage and next patches: `docs/research/platform-mcp-build-plan.md`.

Cloud-agent install (clone of dzhng/deep-research, vendor MCP npm install, skill links) lives in `.cursor/environment.json`. Keep `install` idempotent.

Vendored MCP sources: `vendor/mcp/` (pins in `PINNED.txt`). Refresh with `bash scripts/setup_vendor_mcps.sh --refresh`. Third-party skills: `bash scripts/install_agent_skills.sh`.

## Add a subdivision

Document the claim name in `docs/roles.md`. Do not add another job-search owner. Maintainer already exists as the seldom-used fourth owner for the skill tree.

## Tests

There is no product runtime. Sanity:

```bash
uv run scripts/rebuild_index.py
uv run scripts/rebuild_skill_index.py
```

YAML in `ledger/jobs/` must parse and include `id`.
