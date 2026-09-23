# Process

This is the contract. Skills implement slices of it. If a skill and this document disagree, fix the skill.

jobOS is the job harness. Agents curl `$HUB_URL/llms.txt` and `$HUB_URL/agents.txt` (not HTML) for identity and next steps. **Always use registry skills/MCPs** when Hub is up. If you use something outside, record it and add a memory fact. `review` and `resume` roles are coming soon — stubs only, not part of this contract’s owners. **Deployed agents** (advanced browser handling, cheaper hosted workers) are also coming soon — not shipped, not a claimable track.

## 0. Preconditions

- Hub: finish `/onboarding` so the tenant's `GET /api/candidate/status` has `onboarded: true`. Airgap export: `GET /api/export/ledger`. Never treat git `ledger/` as the live list when Hub is up.
- At least one resume PDF exists in the tenant BlobStore (`PUT /api/candidate/resume`).
- The operator has claimed a role (Hub directory / invites). Do not write claims into git `ledger/INDEX.md` as live state.
- If Hub is up, the operator recalled `GET /api/memory/recall` (worker + track + common) before the cycle. Do not skip it. Do not write memory until there is a durable fact.
- Discovery has a reasonably current `docs/catalogs/skills-and-mcps.md` (or will refresh it first).
- Maintainer, when claimed, also keeps `skills/lists/` in sync with that catalog, and consumes Hub `skill.record`.
- Install/host: [`docs/install.md`](install.md). Cross-agent protocol: [`docs/job-hub/a2a.md`](job-hub/a2a.md). Skill registry contract: [`docs/catalogs/skill-outline.md`](catalogs/skill-outline.md).

## 1. Catalog pass (discovery, first)

Goal: know which skills and MCPs this workspace can actually use.

1. Run [`skills/skill-and-mcp-catalog`](../skills/skill-and-mcp-catalog/SKILL.md).
2. Search more than one registry (skills.sh, Skills Hub, ClawHub, GitHub, mcp.so, Smithery).
3. Vet: license, auth, ToS, whether it applies vs discovers, whether it works airgapped, whether it needs a browser.
4. Write the chosen stack into `docs/catalogs/skills-and-mcps.md` with install notes.
5. If the pass is a platform/MCP coverage refresh, also update `docs/research/platform-mcp-build-plan.md`.
6. If the work is **updating the skill tree** (lists, pruning, example MCP config), load [`skills/skill-maintainer`](../skills/skill-maintainer/SKILL.md) and write `skills/lists/` — that is not a discovery cycle.
7. GitHub starters (`skills/starters/*.yaml` and role `SKILL.md`) plus adopted in-repo skills seed the Hub **skill** registry (`scope=shared`, `status=approved`, `origin=github`) on boot / pack rebuild / migrate. [`skills/lists/`](../skills/lists/) plus `mcp/mcp.example.json` seed the **MCP** registry (`GET /api/registry/mcps`). Lists remain the git inventory — live selection is the Hub DB.
8. When Hub is up, live selection is `GET /api/registry/skills`, not git. Do not install an auto-apply skill into the discovery bot.

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

When Hub is up, pick a matching tagged skill: `GET /api/registry/skills?tag=source` (and `platform` / URL as needed). Airgap: role [`job-discovery`](../skills/job-discovery/SKILL.md) plus `skills/starters/*.yaml`. Do not load another bot’s local skill.

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

1. Dedup against Hub `GET /api/jobs` by apply URL, then by `(company, title, location)`.
2. `POST /api/jobs` if new. Do not treat git `ledger/jobs/` as the live list.
3. Enrich with [`deep-research`](../skills/deep-research/SKILL.md): posting still live, company real, team sketch, red flags.
4. Score 1–5 against the profile. Veto on deal-breakers.
5. If shortlisted, write a complete `apply_packet`. Status becomes `apply_ready` (or `shortlisted` if the human wants a manual gate).
6. If it is a talent network with no job URL, set `apply_kind: network` and still write the packet: how to apply to the network, plus an outreach seed.
7. If the company or the user already said no, set `status: rejected` with `rejection.by` (`company` | `user`) and remarks. Do not keep it in the open pipeline. `skipped` is still for “we passed during sourcing.”

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

When Hub is up, pick a matching tagged skill: `GET /api/registry/skills?tag=apply` (ATS / `url`). Airgap: role [`job-apply`](../skills/job-apply/SKILL.md) plus `skills/starters/*.yaml`. Do not load another bot’s local skill.

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

### 4.5 Rejected

Company emailed a no, or the user does not want this role: `status: rejected`. Set `rejection.by` to `company` or `user`, and put the text in `company_remarks` and/or `user_remarks`. Discovery, apply, and outreach may all do this (`PATCH /api/jobs/{id}`). Do not invent a reason.

## 5. Outreach cycle

Goal: a human conversation. Not a spray.

When Hub is up, pick a matching tagged skill: `GET /api/registry/skills?tag=outreach`. Airgap: role [`job-outreach`](../skills/job-outreach/SKILL.md) plus `skills/starters/*.yaml`. Do not load another bot’s local skill.

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

Every send is a touch on the Hub job (`PATCH /api/jobs/{id}`) and people row (`/api/people`). Status `waiting` until a reply, then `chatting` / `interview` / `offer`. Company or user said no: `rejected` with `rejection.by` (`company` | `user`) and remarks. `closed_rejected` remains valid for an outreach close without structured remarks.

## 6. Shared list hygiene

- Canonical jobs live in Hub Postgres, namespaced by `account_id`.
- Events append in Postgres (`GET /api/events`).
- `GET /api/export/ledger` writes a snapshot tarball when you need git/airgap files.
- Never delete another role’s packet to “clean up.”
- Discovery creates rows only; apply/outreach only advance their fields; **any patch role** may set `status: rejected` plus `rejection` remarks; admin stops/edits. **Maintainer** owns schema and hygiene — see [`board/README.md`](../board/README.md). Operator/agent Hub docs: [`docs/job-hub/human.md`](job-hub/human.md), [`docs/job-hub/agent.md`](job-hub/agent.md). Git `ledger/` is **export-only**, not the live list.

`rejected` is a shared close. It is not lane-scoped. Required: `rejection.by` = `company` | `user`. Optional: `company_remarks`, `user_remarks`. Shorthand: `{ "by": "company", "remarks": "filled internally" }` writes the text onto that party’s remarks field. `closed_rejected` still works for outreach; prefer `rejected` when you know who said no.

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
- If Hub ran: memory was recalled this round; only durable facts were stored (see [`docs/job-hub/memory.md`](job-hub/memory.md)); track/common facts that should become skills were solidified
- If maintainer ran: `skills/lists/INDEX.md` matches the YAML lists
- If Hub is up: GitHub starters were seeded into the registry; no un-proctored shared skills from other bots

## 10. Maintainer pass (seldom)

Goal: keep the skill/MCP inventory true, keep the Hub registry honest, and keep the hunt board honest. **No job sourcing.**

1. Claim `maintainer` on `ledger/INDEX.md`.
2. Load [`skills/skill-maintainer`](../skills/skill-maintainer/SKILL.md).
3. Search at least two registries. Vet. Write `skills/lists/{adopted,wanted,rejected,by-platform,sources}.yaml`.
4. `uv run scripts/rebuild_skill_index.py`.
5. Patch `mcp/mcp.example.json` / `.cursor/environment.json` only for tools that moved to **adopted**.
6. **Skill registry:** claim `skill.record` (maintenance only). Proctor first against the [`skill-outline`](catalogs/skill-outline.md) rubric. Promote only on pass. Fail with a note; the submitter may keep the local copy. Memory facts that were solidified stay in this same queue (`origin=memory`).
7. Anyone (any track) may enqueue a recording (`POST /api/registry/recordings` or queue push `skill.record`). Only maintainer / admin **consumes**.
8. Seed / re-seed GitHub starters (`POST /api/registry/seed`) if needed. Does not overwrite promoted non-github shared slugs.
9. Append catalog workspace log + `ledger/events.jsonl`.
10. Hunt board (when this hunt uses one): generate/rotate tokens with `scripts/board_gen_tokens.py`, keep `board/start.sh` up, import ledger history if needed, run hygiene. Tokens stay gitignored.

Do not start a discovery search from this pass.
