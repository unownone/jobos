# Shared ledger

Git is the **airgap protocol**. Discovery owner keeps INDEX honest. See [docs/sharing.md](../docs/sharing.md).

When a hunt runs on a shared machine, the live coordination plane is the maintainer-owned board in [`board/`](../board/README.md). This folder stays: YAML per job, people, events, schema. Do not treat the board as permission to delete the ledger.

- `jobs/` — one YAML file per posting or network target (`_example.yaml` is not live work)
- `people/` — contacts for outreach
- `events.jsonl` — append-only
- `schema/` — contracts for the YAML

Do not commit real candidate jobs to a public fork of this template. Use a private live repo with the same layout. Do not commit board tokens or `board/data/*.db`.
