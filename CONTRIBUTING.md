# Contributing to the template

This repo is **jobOS**, a job harness — not a live job search. Keep PII and live ledgers out of public history.

## Change the process, then the skills

1. Edit `docs/process.md` (contract)
2. Align `docs/architecture.md` / `docs/roles.md` / `docs/sharing.md` if the motion changed
3. Update the matching `skills/*/SKILL.md` (Claude agents see the same files via `.claude/skills` → `../skills`)
4. If you added or dropped a tool, update `skills/lists/` and keep `skills/lists/INDEX.md` in sync
5. Update catalogs if portals or MCPs changed

Skills should stay short and point at docs. Do not fork the status enum in three places — `ledger/schema/job.schema.json` is the list of statuses (Hub jobs use the same enum).

## Add a platform

Add a row to `docs/catalogs/platforms.md` or `big-tech-careers.md`. If it needs a tool, run the catalog skill (or the **maintainer** skill if you are updating lists) and log it in `docs/catalogs/skills-and-mcps.md` plus `skills/lists/`. Coverage and next patches: `docs/research/platform-mcp-build-plan.md`.

Cloud-agent install (clone of dzhng/deep-research, vendor MCP npm install, skill links) lives in `.cursor/environment.json`. Keep `install` idempotent.

MCP pins (`uvx` / git SHA, no source trees): `vendor/mcp/PINNED.txt`. Refresh caches with `bash scripts/setup_vendor_mcps.sh`. Third-party skills: `bash scripts/install_agent_skills.sh`.

## Add a subdivision

Document the claim name in `docs/roles.md`. Do not add another job-search owner. Maintainer already exists as the seldom-used fourth owner for the skill tree and hunt board.

## Tests

Hub API:

```bash
cd server && go test ./...
```

SPA build:

```bash
cd web && npm ci && npm run build
```

Export snapshots (`GET /api/export/ledger`) may still write `ledger/jobs/*.yaml` for airgap copies. Those files are not the live list.

```bash
make deploy-check
```
