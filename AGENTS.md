# Agent operating rules

You are working in **Job Apply OS**. Read this before doing anything else.

## Identity

1. Read `profiles/candidate.yaml`. If it is missing, copy `profiles/candidate.example.yaml` and stop for the human to fill it in. Do not invent a candidate.
2. Read `docs/process.md` if you have not already this session.
3. Claim a role from `docs/roles.md`. Write the claim into `ledger/INDEX.md` under **Active operators**.

If the user says you own everything, you still run the three roles **in order**: catalog + research + discovery, then apply, then outreach. Never Easy Apply during discovery. Maintainer is a fourth owner and is **seldom** used; run it when the skill/MCP inventory is the work, not mid-search.

## Role picker

| If the user says | Load |
| --- | --- |
| discover, source, shortlist, find jobs | `skills/job-discovery/SKILL.md` |
| apply, submit, cover letter, easy apply | `skills/job-apply/SKILL.md` |
| outreach, email, LinkedIn DM, referral, hiring manager | `skills/job-outreach/SKILL.md` |
| find skills, find MCPs, skillhub, skills.sh | `skills/skill-and-mcp-catalog/SKILL.md` |
| research the company, find the hiring manager, deep research | `skills/deep-research/SKILL.md` |
| maintain, update skills, manage catalog, skill lists | `skills/skill-maintainer/SKILL.md` |

Discovery **starts** with the catalog skill unless `docs/catalogs/skills-and-mcps.md` was updated this week. If the work is **updating the skill tree itself** (lists, mcp.example.json, pruning dead tools), that is the seldom-used **maintainer** role, not discovery.

## Hard rules

- Do not fabricate experience, employers, dates, or metrics.
- Do not apply during discovery. Easy Apply counts as applying.
- Do not send SMS, WhatsApp, or InMail sequences unless the user explicitly adds that channel later. Default channels are **email** and **LinkedIn DMs**.
- Do not dump credentials into the ledger. Put secrets in gitignored files.
- Do not scrape authenticated pages you do not have an account for.
- Prefer official APIs, public JSON feeds, and public career pages.
- Attach PDFs on **email**. LinkedIn DMs usually cannot take a PDF; send a short note and ask for a chat, and point at a resume link if you have one.
- Every state change gets a row in `ledger/events.jsonl` and an update on the job YAML.

## Ledger writes

Canonical record: `ledger/jobs/<id>.yaml`

- Create a new file when discovering a new job.
- Update in place for status, packets, and notes.
- Append to `ledger/events.jsonl`.
- Refresh the matching row in `ledger/INDEX.md` (or run `uv run scripts/rebuild_index.py`).

If two bots touched the same file, keep both packets, do not delete the other role’s fields, and leave a `conflicts` note.

## Voice

Applications and outreach should be specific, short, and worth reading. No “passionate synergistic self-starter.” Proof over adjectives. Match the company’s language only when it is already in the posting or in sourced research.

## When blocked

Write `apply_blocked` or a `blocked` note with the exact missing thing (login, work auth question, missing PDF, captcha, portal down). Do not pretend you submitted.
