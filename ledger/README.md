# Shared ledger

Git is the **airgap protocol**. Discovery owner keeps INDEX honest. See [docs/sharing.md](../docs/sharing.md).

When a hunt runs on a shared machine, the live coordination plane is the maintainer-owned Hub (Go API + React SPA). This folder stays: YAML per job, people, events, schema — an export/airgap snapshot, not a second live board.

- `jobs/` — one YAML file per posting or network target (`_example.yaml` is not live work)
- `people/` — contacts for outreach
- `events.jsonl` — append-only
- `schema/` — contracts for the YAML

Do not commit real candidate jobs to a public fork of this template. Use a private live repo with the same layout. Do not commit `.hub/.env` or Hub secrets.
