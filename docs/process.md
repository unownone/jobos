# Process

This is the contract. Skills implement slices of it. If a skill and this document disagree, fix the skill.

## 0. Preconditions

- Hub: finish `/onboarding` so `GET /health` has `candidate_onboarded: true`. Airgap: `profiles/candidate.yaml` exists and is truthful (never the example file as live data).
- At least one resume PDF exists locally or on the Hub (`PUT /api/candidate/resume`).
- The operator has claimed a role in `ledger/INDEX.md`.
- Discovery has a reasonably current `docs/catalogs/skills-and-mcps.md` (or will refresh it first).
- Maintainer, when claimed, also keeps `skills/lists/` in sync with that catalog.
- Install/host: [`docs/install.md`](install.md). Cross-agent protocol: [`docs/job-hub/a2a.md`](job-hub/a2a.md).

## 1. Catalog pass (discovery, first)

Goal: know which skills and MCPs this workspace can actually use.

1. Run [`skills/skill-and-mcp-catalog`](../skills/skill-and-mcp-catalog/SKILL.md).
2. Search more than one registry (skills.sh, Skills Hub, ClawHub, GitHub, mcp.so, Smithery).
3. Vet: license, auth, ToS, whether it applies vs discovers, whether it works airgapped, whether it needs a browser.
4. Write the chosen stack into `docs/catalogs/skills-and-mcps.md` with install notes.
5. If the pass is a platform/MCP coverage refresh, also update `docs/research/platform-mcp-build-plan.md`.
6. If the work is **updating the skill tree** (lists, pruning, example MCP config), load [`skills/skill-maintainer`](../skills/skill-maintainer/SKILL.md) and write `skills/lists/` — that is not a discovery cycle.
7. Do not install an auto-apply skill into the discovery bot.

## 2. Profile freeze

Goal: every bot scores jobs the same way.

Lock for the cycle:

- Target titles and seniority
- Locations / remote
- Must-haves and deal-breakers
- Daily caps
- Easy Apply policy (default: never in discovery)

If the human changes the profile mid-cycle, finish in-flight packets, then re-score `discovered` and `enriching` jobs.

## 3. Discovery cycle

Goal: a shortlist with reproducible apply packets. **No applications.**

### 3.1 Coverage

Work the platform catalog in [`docs/catalogs/platforms.md`](catalogs/platforms.md). Minimum viable coverage for a first cycle:

1. Indeed MCP if authenticated, else Indeed public search
2. LinkedIn Jobs search (list only — do not click Easy Apply)
3. Work at a Startup
4. Wellfound
5. Google Jobs + dorks against Greenhouse / Lever / Ashby / Workday
6. RemoteOK public API
7. Hiring Cafe (`scripts/fetch_hiringcafe.py` / hiring.cafe public pages)
8. Named marketplaces (Flexiple, Turing, Weekday, Toptal, Lemon.io, BairesDev, Roro Remote) — record whether each item is a **posting** or a **network apply**
9. Big-company career sites the candidate cares about

### 3.2 For every raw hit

1. Dedup against `ledger/jobs/` by apply URL, then by `(company, title, location)`.
2. Create `ledger/jobs/<id>.yaml` if new.
3. Enrich with [`deep-research`](../skills/deep-research/SKILL.md): posting still live, company real, team sketch, red flags.
4. Score 1–5 against the profile. Veto on deal-breakers.
5. If shortlisted, write a complete `apply_packet`. Status becomes `apply_ready` (or `shortlisted` if the human wants a manual gate).
6. If it is a talent network with no job URL, set `apply_kind: network` and still write the packet: how to apply to the network, plus an outreach seed.

### 3.3 Apply packet bar

A packet is done only if another bot can apply tomorrow without this chat. Required fields are in [`handoffs/apply-packet.md`](../handoffs/apply-packet.md).

Especially:

- Exact apply URL
- ATS or portal name
- Account required? which email?
- Documents to upload
- Visible screening questions
- Step list (numbered, boring, reproducible)
- Why this role is on the shortlist (three lines, evidence-based)
- `do_not_apply_yet: true` stays true until apply claims it

### 3.4 Discovery stop conditions

Stop the cycle when:

- `max_shortlist_per_cycle` is hit, or
- Portals in scope were covered, or
- The user asks to freeze the list

Never “just knock out a few Easy Applies” to feel productive.

## 4. Apply cycle

Goal: submit a small number of high-quality applications.

### 4.1 Claim

Only take jobs in `apply_ready` (or `shortlisted` if the human approved them). Set `owners.apply` and `status: applying` before touching a portal.

### 4.2 Write

Use [`skills/job-apply`](../skills/job-apply/SKILL.md). Standard:

- Specific to this JD and this company
- Short enough to read on a phone
- Proof from the candidate profile / resume only
- One sentence that could only have been written for this company
- No templates that start with “I am writing to express”

If deep research found a real product or team detail, use it. If it is shaky, skip it.

### 4.3 Submit

Follow the packet steps. Do not improvise a different URL. If the posting died, mark `closed_expired` and tell discovery.

Save proof in the job YAML:

- Timestamp
- Confirmation text or URL
- Screenshot path if you have one
- What was uploaded
- Exact message / answers submitted

Then set `status: applied` and seed `outreach_packet`.

### 4.4 Blocked

If a portal needs a human (captcha, government ID upload, unknown work-auth question), set `apply_blocked` with the exact blocker. Do not guess legal answers.

## 5. Outreach cycle

Goal: a human conversation. Not a spray.

### 5.1 When

Default: only after `applied`, or when `apply_kind: network` / `apply_kind: outreach_only`.

### 5.2 Who

Use deep research to name:

1. Hiring manager or recruiter on the posting
2. A teammate in the same function
3. Optionally a founder / exec at small companies — not at Amazon-scale unless the user asks

Cap: `max_outreach_touches_per_person` from the profile (default 2).

### 5.3 Channels

| Channel | How | Asset |
| --- | --- | --- |
| Email | Draft (prefer Gmail MCP) then send or leave for human | **Attach the PDF**. This is required. |
| LinkedIn DM | Short note, ask for a 15-minute chat | No PDF expected; include a link if you have one |

No SMS. No random other messengers.

If the email MCP cannot attach files, do not send a bare email and call it done. Write the draft locally, encode the PDF as base64 on `attachments`, or leave a blocked note. Gmail `create_draft` supports `attachments[{filename, mimeType, content}]`.

### 5.4 Ask

The ask is always: **a short chat**. Not “please hire me.” Not a novel.

### 5.5 Log

Every send is a touch on the job YAML and a people file under `ledger/people/`. Status `waiting` until a reply, then `chatting` / `interview` / `closed_rejected`.

## 6. Shared list hygiene

- One job file per posting in git (`ledger/jobs/`).
- INDEX.md is the human git board. Rebuild it if it drifts.
- Events are append-only (`ledger/events.jsonl`, and `board` events when the live board is up).
- Discovery owner resolves **git** merge conflicts.
- Never delete another role’s packet to “clean up.”
- If the live hunt board / Job Hub is running (`HUB_URL` / `BOARD_URL`): discovery creates rows only; apply/outreach only advance their fields; admin stops/edits. **Maintainer** owns tokens, schema, and hygiene — see [`board/README.md`](../board/README.md). Operator/agent Hub docs: [`docs/job-hub/human.md`](job-hub/human.md), [`docs/job-hub/agent.md`](job-hub/agent.md). Git ledger remains the airgap protocol.

## 7. Quality gates

| Gate | Fail if |
| --- | --- |
| Discovery | Packet missing URL or steps; Easy Apply was clicked; duplicates in INDEX |
| Apply | Generic letter; no proof; submitted a different job than the packet |
| Outreach | Email without PDF; more than cap touches; DM that reads like a blast |

## 8. Cadence

Suggested, not mandatory:

- Discovery: 1–2 cycles per day, then freeze
- Apply: drip under `max_applies_per_day`
- Outreach: same day or next day after apply, then wait

## 9. Definition of done for a cycle

- INDEX.md matches the YAML files
- Every `apply_ready` job has a packet
- Every `applied` job has proof and an outreach seed
- Every outreach touch has a person record
- Catalog notes any tool that failed, so the next bot does not rediscover a dead MCP
- If maintainer ran: `skills/lists/INDEX.md` matches the YAML lists

## 10. Maintainer pass (seldom)

Goal: keep the skill/MCP inventory true, and keep the hunt board honest. **No job sourcing.**

1. Claim `maintainer` on `ledger/INDEX.md`.
2. Load [`skills/skill-maintainer`](../skills/skill-maintainer/SKILL.md).
3. Search at least two registries. Vet. Write `skills/lists/{adopted,wanted,rejected,by-platform,sources}.yaml`.
4. `uv run scripts/rebuild_skill_index.py`.
5. Patch `mcp/mcp.example.json` / `.cursor/environment.json` only for tools that moved to **adopted**.
6. Append catalog workspace log + `ledger/events.jsonl`.
7. Hunt board (when this hunt uses one): generate/rotate tokens with `scripts/board_gen_tokens.py`, keep `board/start.sh` up, import ledger history if needed, run hygiene. Tokens stay gitignored.

Do not start a discovery search from this pass.
