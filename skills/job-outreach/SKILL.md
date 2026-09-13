---
name: job-outreach
description: After an application (or for network-only targets), reach out by email and LinkedIn DM. Attach the resume PDF on email. Ask for a short chat. Find hiring managers, teammates, or execs at small companies via deep research. Use when following up, asking for referrals, or when email attachments previously failed. No SMS.
role: outreach
tags: [outreach]
kind: skill
slug: job-outreach
reproducible: true
inputs: [job, outreach_packet, candidate]
outputs: [touches]
---

# Job outreach

You get a conversation. You do not apply. You do not text.

## Registry

When `HUB_URL` is set, use tagged `outreach` skills (`outreach-email`, `outreach-linkedin-dm`) from `GET /api/registry/skills?tag=outreach`. Local copy edits stay local. Recordings go to the maintainer queue. Airgapped: this playbook.

Outline: `docs/catalogs/skill-outline.md`.

## Startup sequence

1. Take `status: applied` or `apply_kind: network|outreach_only` jobs that are `outreach_ready` or still missing touches.
2. Claim `owners.outreach`.
3. Run `skills/deep-research/SKILL.md` in people-map mode unless `outreach_packet.people` is already filled with URLs.
4. Write `ledger/people/<id>.yaml` for each contact.
5. If Hub is up, recall `/api/memory/recall` (common + outreach track) before sending. Store a `person_hint` only when a contact path would save the next outreach worker a search — never dump emails or tokens.

## Channels

### Email (required when an email is verified or provided)

- Draft first. Prefer Gmail MCP `create_draft`.
- **Attach the PDF.** Read the file, base64 it, pass `attachments: [{ filename, mimeType: "application/pdf", content }]`.
- If attachment fails, do not send a naked email. Mark `blocked: attachment` and fix.
- Subject: specific (`Google Maps platform — Ada, Staff SWE app`).
- Body: 6–10 lines. Who you are, what you applied to (link), one proof, ask for a 15-minute chat, resume attached.

### LinkedIn DM

- No PDF expected.
- 4–7 lines. Same ask: a short chat. Link the job or the email thread if useful.
- Do not InMail-blast. Do not scrape the inbox.

No SMS, WhatsApp, or other messengers unless the user adds a channel in writing.

## Who

Order: recruiter on the posting → hiring manager → teammate in-function → founder/exec **only at small companies**. Mega-cap CEOs are out of scope by default.

Cap touches per person from the profile. Log every attempt.

## Copy helpers (optional)

If `.agents/skills/draft-outreach` or `compose-outreach` is linked, use them to draft. They must not send. Common Room MCP is optional — if it is missing, skip CR tools and use the ledger people file + deep-research. Email still goes through Gmail MCP with the PDF attached.

## Templates

Start from `assets/templates/email.md` and `assets/templates/linkedin-dm.md`, then specialize. If it could be sent to ten companies unchanged, rewrite.

## Status

- After send: `waiting`
- Reply: `chatting` (or `interview` if they propose a loop)
- No reply after the cap: note `exhausted` on the person, move on

If the hunt board is up (`BOARD_URL` + outreach token from maintainer): PATCH only outreach fields. Do not own the board. See [`board/README.md`](../../board/README.md).

## Failure mode you must not repeat

“Messages currently failing to attach PDFs.” Treat a sent email without the resume as a failed touch. Fix the draft tool call, then retry.
