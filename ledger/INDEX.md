# Ledger INDEX

Human board. Canonical data lives in `jobs/*.yaml`. Rebuild with `uv run scripts/rebuild_index.py`.

## Active operators

| role | name | scope | since |
| --- | --- | --- | --- |
| discovery | cursor-cloud-agent | catalog + research (no apply, no Easy Apply) | 2026-09-06 |
| apply | _unclaimed_ | all ATS | |
| outreach | _unclaimed_ | email + linkedin_dm | |

## Jobs

| id | company | title | source | status | score | owner | next |
| --- | --- | --- | --- | --- | --- | --- | --- |
| _empty_ | | | | | | | clone example from `jobs/_example.yaml` when live |

## How to update

1. Edit or add `ledger/jobs/<id>.yaml`
2. Append one line to `events.jsonl`
3. Refresh the row above (or run the rebuild script)
