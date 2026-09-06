# Contributing to the template

This repo is the **operating system**, not a live job search. Keep PII and live ledgers out of public history.

## Change the process, then the skills

1. Edit `docs/process.md` (contract)
2. Align `docs/architecture.md` / `docs/roles.md` / `docs/sharing.md` if the motion changed
3. Update the matching `skills/*/SKILL.md`
4. Update catalogs if portals or MCPs changed

Skills should stay short and point at docs. Do not fork the status enum in three places — `ledger/schema/job.schema.json` is the list.

## Add a platform

Add a row to `docs/catalogs/platforms.md` or `big-tech-careers.md`. If it needs a tool, run the catalog skill and log it in `docs/catalogs/skills-and-mcps.md`. Coverage and next patches: `docs/research/platform-mcp-build-plan.md`.

Cloud-agent install (clone of dzhng/deep-research, etc.) lives in `.cursor/environment.json`. Keep `install` idempotent.

## Add a subdivision

Document the claim name in `docs/roles.md`. Do not add a fourth top-level owner unless the human asks.

## Tests

There is no product runtime. Sanity:

```bash
uv run scripts/rebuild_index.py
```

YAML in `ledger/jobs/` must parse and include `id`.
