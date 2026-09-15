# Ledger INDEX

Human board. Canonical data lives in `jobs/*.yaml`. Rebuild with `uv run scripts/rebuild_index.py`.

## Active operators

| role | name | scope | since |
| --- | --- | --- | --- |
| discovery | cursor-cloud-agent | catalog + research (no apply, no Easy Apply) | 2026-09-06 |
| apply | _unclaimed_ | all ATS | |
| outreach | _unclaimed_ | email + linkedin_dm | |
| maintainer | cursor-cloud-agent | skills + lists + hunt board | 2026-09-06 |
| maintainer | cursor-cloud-agent (job-hub-skeleton) | Job Hub phase A: deploy + admin bootstrap (no discovery/apply/outreach) | 2026-09-07 |
| maintainer | cursor-cloud-agent (job-hub-auth) | Job Hub phase B: invites, owners, agent keys, admin login (no discovery/apply/outreach) | 2026-09-07 |
| maintainer | cursor-cloud-agent (job-hub-presence) | Job Hub phase C: heartbeat, presence, admin directory (no discovery/apply/outreach) | 2026-09-07 |
| maintainer | cursor-cloud-agent (job-hub-queue) | Job Hub phase D: queue claim/ack/leases (no discovery/apply/outreach) | 2026-09-07 |
| maintainer | cursor-cloud-agent (job-hub-onboarding) | Job Hub phase E: /api/onboarding + skill/MCP/script packs (no discovery/apply/outreach) | 2026-09-07 |
| maintainer | cursor-cloud-agent (job-hub-messages) | Job Hub phase G: inter-agent inbox APIs (no discovery/apply/outreach) | 2026-09-07 |
| maintainer | cursor-cloud-agent (job-hub-board-api) | Job Hub phase F: people + ledger export + catalog gate + board UI hub (no discovery/apply/outreach) | 2026-09-07 |
| maintainer | cursor-cloud-agent (job-hub-docs) | Job Hub phase H: operator + agent docs (no discovery/apply/outreach) | 2026-09-07 |
| maintainer | cursor-cloud-agent (a2a-onboard-docker) | Mandatory `/onboarding` gate + A2A protocol + Docker/Compose install docs (no discovery/apply/outreach) | 2026-09-12 |
| maintainer | cursor-cloud-agent (skill-registry) | skill registry + starters + proctor queue (no discovery/apply/outreach) | 2026-09-13 |
| maintainer | cursor-cloud-agent (hub-memory-pods) | Hub memory layer: worker / track / common pods in SQLite FTS (no extra Compose service) | 2026-09-13 |
| maintainer | cursor-cloud-agent (skill-registry-memory) | merge memory pods onto registry; solidify track/common facts into origin=memory recordings | 2026-09-13 |
| maintainer | cursor-cloud-agent (skill-memory-e2e) | in-process e2e for registry + memory solidify + catalog refresh unlock | 2026-09-15 |
| maintainer | cursor-cloud-agent (ssh-deploy-runner) | GitHub SSH-over-443 deploy keys + PR deploy-check workflow (no discovery/apply/outreach) | 2026-09-15 |

## Jobs

| id | company | title | source | status | score | owner | next |
| --- | --- | --- | --- | --- | --- | --- | --- |
| _empty_ | | | | | | | clone example from `jobs/_example.yaml` when live |

## How to update

1. Edit or add `ledger/jobs/<id>.yaml`
2. Append one line to `events.jsonl`
3. Refresh the row above (or run the rebuild script)
