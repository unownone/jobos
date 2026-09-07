# Sharing (airgapped-first)

The **git repo is the airgap protocol**. Hosting is optional. Discovery owner is the git-ledger portal owner.

When agents share a machine, **maintainer** runs the live hunt board in [`board/`](../board/README.md). That board is the practical coordination UI/API for the hunt. It does not delete or replace `ledger/`.

## Why git

Apply and outreach bots may have:

- No Indeed OAuth
- No Skill registry
- No research API keys
- No always-on network except “pull this repo”

They still need the shortlist, the packets, and a place to write results. Files work. A server does not, until someone volunteers to run one.

## Canonical store

```
ledger/
  INDEX.md              Human board. Everyone can read. Discovery keeps it true.
  events.jsonl          Append-only audit.
  jobs/<id>.yaml        One posting (or network target) per file.
  people/<id>.yaml      One human contact per file.
  schema/               Contracts.
```

One file per job is the merge strategy. Do not put all jobs in a single JSON array.

## Write protocol

1. `git pull` (or copy the folder) before you edit.
2. Claim the job in YAML (`owners.*`, status).
3. Edit only your fields when possible.
4. Append one event line.
5. Update the INDEX row for that id.
6. `git push` if you can. If you cannot, hand the files to the discovery owner.

### Event line

```json
{"ts":"2026-09-06T15:00:00Z","job_id":"remoteok__123","actor":"discovery-1","role":"discovery","from":null,"to":"discovered","note":"from remoteok api"}
```

Never edit old event lines.

## INDEX.md

The board everyone can scan. Columns:

| id | company | title | source | status | score | owner | next |
| --- | --- | --- | --- | --- | --- | --- | --- |

`next` is a short instruction: `apply packet ready`, `send email+dm`, `waiting on recruiter`, `blocked: captcha`.

If you cannot run Python, edit INDEX by hand. If you can:

```bash
uv run scripts/rebuild_index.py
```

## Conflict rules

| Situation | Resolution |
| --- | --- |
| Two discoveries, same apply URL | Keep one file. Merge notes. Lower id wins if both exist. |
| Apply and outreach edit the same file | Keep both packets. Do not drop fields. |
| Disagree on score | Discovery owner decides; leave the other score in `notes`. |
| Disagree on “skip” | Skip needs a reason. Human / discovery owner breaks ties. |
| Cannot push | Discovery owner ingests the files. |

Add:

```yaml
conflicts:
  - ts: "..."
    note: "apply bot could not push; packet is in this file"
```

## Optional live hunt board (maintainer-owned)

Use [`board/`](../board/README.md) when several bots share a host and need a single live list without waiting on git push.

**Maintainer owns it:** token generation/rotation, process hygiene, schema, uptime, and any tunnel. Discovery/apply/outreach get a role token from the maintainer and only write their lane.

- Local: `http://127.0.0.1:8787/` on the shared machine (server binds `0.0.0.0`).
- Sibling agents: same host, `X-Role` + `X-Token`.
- Optional temporary public tunnel (`localtunnel` / `cloudflared`): exposes the board. Prefer admin auth always. Tear it down after. **Group chats cannot host connect cards** or live iframes; do not paste tokens there.

Write rules: discovery creates rows; later lanes only advance their fields; admin can stop/edit. Details and curl examples: [`board/README.md`](../board/README.md).

## Optional overlays

Use these only as mirrors. They are not source of truth.

| Overlay | Owner | Use |
| --- | --- | --- |
| Google Sheet | Discovery | Humans who will not open git |
| Google Drive folder | Discovery | PDF proof, extra resumes |
| Local `ledger/.cache` | Anyone | Search indexes, gitignored |

If Drive is used, discovery pastes the folder id into `profiles/candidate.yaml` or `.env` as `GOOGLE_DRIVE_LEDGER_FOLDER_ID`. Other bots may append if they have the MCP. They still write git first.

## What not to share in git

- Session cookies
- MCP OAuth tokens
- Full `.env`
- Government IDs
- Live `candidate.yaml` if the repo is public (use the example + private overlay)

Public template repos should keep **schema and examples** only. Forks used for a real search can make `ledger/jobs/` private or use a private sibling repo. A simple pattern:

- Public: this template
- Private: `job-apply-os-live` with real ledger + profile, same schema

## Airgap matrix

| Bot | Needs network to | Can work from files only |
| --- | --- | --- |
| Discovery | Job portals, research MCP, skill registries | No (except re-scoring an existing ledger) |
| Apply | Target ATS / LinkedIn | Yes for writing; no for submit |
| Outreach | Gmail + LinkedIn | Yes for drafting; no for send |

Discovery is the only role that *must* be less airgapped. That matches “at most one owner holds the portal.”
