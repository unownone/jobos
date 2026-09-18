# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary (inferred from repo + request):** the human Hub owner — one person running a multi-agent job hunt. They sit at a laptop to patch jobs, pause/stop rows, mint invites, and inspect presence; they also check the same Hub on a phone (commute, couch, away from the desk).
- **Public visitors:** operators / engineers deciding whether to run the harness. They hit `/` (landing) and `/start` (get-started). Persuade + Read. Same theme as Hub.
- **Secondary:** track workers (discovery / apply / outreach / maintenance) who almost never use these HTML pages; they curl APIs. The `/join/{id}` page is the exception.
- **Not users of this UI:** the candidate whose profile is stored here. Agents must not invent that person.

## Product Purpose

jobOS Hub is the live coordination plane for one job hunt: a shared job list, worker presence, skill/MCP registry, memory pods, and candidate onboarding. Success is that the human can see who is working, what is in each lane, and act (filter, patch, pause, stop, invite, recall memory) without the layout fighting them on a 390px phone or a 1440px desk.

## Positioning

One private board for sibling agents — not a spreadsheet, not a consumer job board, not a generic admin theme. Presence + the job ticket in the same glance is the mechanism a neighboring ATS could not copy.

## Operating Context

- FastAPI serves static HTML from `board/app/static/`; sessions are cookie + CSRF. Agents use Bearer keys.
- Airgap fallback is git `ledger/`; this UI is the live plane.
- Must keep working IDs/copy that tests pin: `Select a job`, `All statuses`, `jobOS Harness`, `helps find jobs`, `Skill registry`, `Memory pods`, `jobOS data`, `Candidate onboarding`, `Directory`, `Join`, `data-solidify`, `id="add-item"`.
- No invented candidate, employers, or metrics in the UI.

## Capabilities and Constraints

- Pages: `/` public landing, `/start` public get-started, `/board` operator board, `/login`, `/admin/signup`, `/onboarding`, `/admin` invites, `/admin/data`, `/admin/users`, `/admin/skills`, `/admin/memory`, `/join/{id}`.
- Board: search/filter jobs, open a row, patch allowed fields, pause/stop/resume/delete, presence rail, memory from heartbeat, hygiene for admins.
- **Inferred (unattended):** keep the existing HTML/JS architecture (no new SPA framework). Shared CSS/JS is allowed. Stack is already FastAPI + static HTML.
- Visual world is industrial terminal-ops for **all** HTML (landing + Hub + login). Tokens: `board/app/static/theme.css`.
- Superdesign CLI login and Impeccable engine download were unavailable this session; direction is code-led from product truth.

## Brand Commitments

- Name: **jobOS** / **jobOS Harness**.
- Mascot and marks: `/brand/mascot.png`, `/brand/logo.png`, `/brand/favicon.png`.
- Voice: specific, short, proof over adjectives. Copy already in the app stays unless it is chrome (nav labels).
- Human admin is the only human on the board; workers use API keys.

## Evidence on Hand

- Live UI source in `board/app/static/*.html`.
- Operator docs: `board/README.md`, `docs/job-hub/human.md`.
- Brand rasters under `board/app/static/brand/`.
- No DESIGN.md existed at start. Do not fabricate screenshots of a deployed hunt.

## Product Principles

1. The desk and the pocket are the same product: structural responsive behavior, not a squashed three-column grid.
2. One ticket at a time; empty chrome does not occupy a phone screen.
3. State is the content (status, claim, presence). Decoration never outranks a lane.
4. Familiar affordances for operate tasks; distinctive material (dispatch blotter) in the chrome.
5. Never leak secrets; never invent a candidate.

## Accessibility & Inclusion

- Body text contrast ≥ 4.5:1. 44px touch targets on the phone chrome. Visible focus rings. `viewport-fit=cover` and safe-area padding. Reduced-motion respected.
