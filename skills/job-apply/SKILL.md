---
name: job-apply
description: Apply to shortlisted jobs in Job Apply OS with specific, worth-reading materials. Follows apply packets only. Use when submitting applications, Easy Apply after discovery, Greenhouse/Lever/Workday forms, or writing cover notes. Never invent jobs or start cold outreach.
role: apply
tags: [apply]
kind: skill
slug: job-apply
reproducible: true
inputs: [job, apply_packet, candidate]
outputs: [proof, outreach_packet]
---

# Job apply

You submit. You do not source. You do not cold-email.

## Capability gate

If you are on jobOS MCP, call `evaluate_lane` with `apply` before any step below. Apply needs a browser in this agent session. If `can` is false, tell the human and stop. Do not type an application into chat and call it submitted. If this session does not include apply, ask the human before adding it with `set_session_lanes`.

## Registry

When `HUB_URL` is set, pick the tagged `apply` skill that matches the packet ATS/URL (`GET /api/registry/skills?tag=apply&ats=workday` or `&url=`). Workday on job A is Workday on job B. Tenant quirks stay on a **local** fork (`POST /api/registry/skills/{id}/fork`). Others cannot see that fork. To share, `POST /api/registry/recordings` — only maintainer consumes `skill.record`. Airgapped: follow this role skill.

Outline: `docs/catalogs/skill-outline.md`.

## Startup sequence

1. Read `profiles/candidate.yaml`, or `GET /api/candidate/public` on the Hub. If neither gives a profile, stop for the human to finish `/onboarding`. Fetch the resume with `GET /api/candidate/resume` when the packet needs the PDF.
2. Take jobs with `status: apply_ready` (or `shortlisted` if the user approved).
3. Claim `owners.apply` and set `applying` before opening a portal.
4. Follow `apply_packet` in the YAML. If the packet is incomplete, bounce to discovery (`apply_blocked: packet incomplete`) instead of guessing a URL.
5. If Hub is up, recall `/api/memory/recall?company=` for this employer before opening the ATS. Store a `portal_quirk` or `blocker` only when the packet was wrong or the site did something another applicator must know.

## Writing bar

The message must be worth reading. If you would skim it, rewrite it.

- First line: why this team, with a fact from the JD or cited research
- Middle: two proof bullets from the resume / profile, mapped to their requirements
- Close: availability + ask to continue
- Length: about half a page or less. Easy Apply notes: 800–1200 characters unless they ask for more
- Voice: from `candidate.yaml` `materials.writing_voice`
- Never fabricate. Never “I led a 40-person org” if the resume does not say so
- No “I am writing to express my interest.” No emoji unless they used one first

Optional: load `assets/templates/cover-letter.md` as a skeleton, then throw away anything generic.

Use `skills/deep-research/SKILL.md` only to fetch **one** usable fact. If research is thin, stay close to the JD.

## Submit

- Use the packet steps in order
- Upload the named PDF
- Answer screening questions from the profile; if unknown, `apply_blocked`
- Easy Apply is allowed **here**, not in discovery
- Browser: Playwright MCP and/or `.agents/skills/playwright-cli` (apply env only)
- Respect `max_applies_per_day`

## Proof (required)

```yaml
proof:
  submitted_at: "2026-09-06T18:00:00Z"
  confirmation: "text or URL"
  artifacts: []  # screenshot paths if any
  uploaded: ["assets/resume/resume-primary.pdf"]
  answers_summary: "work auth: yes; notice: 30 days"
```

Then `status: applied` and seed `outreach_packet` from `handoffs/outreach-packet.md` (people can be empty; outreach fills them).

## Blocked

Captcha, OTP, government ID, legal questions you cannot answer, dead link: `apply_blocked` with the exact next human action.

Company said no, or the user does not want this role: `status: rejected` with `rejection.by` (`company` | `user`) and remarks (`company_remarks` / `user_remarks`). Any apply bot may do this. Do not invent a reason.

If the hunt board is up (`BOARD_URL` + apply token from maintainer): PATCH only apply fields on that row. Do not own the board; do not rotate tokens. See [`board/README.md`](../../board/README.md).
