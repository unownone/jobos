# Sharing

Canonical state is **jobOS Hub**: Postgres when configured, plus the blob driver, namespaced by account id. Queue leases are `queue_items` rows. Git is the source repo for skills and docs, not the live job list.

Sign up at `/login` (username + password). No dashboard token. Each account only sees its own jobs, files, skills, memory, and queue traffic.

Hub operator/agent runbooks: [`docs/job-hub/human.md`](job-hub/human.md), [`docs/job-hub/agent.md`](job-hub/agent.md). Design: [`docs/job-hub/multi-tenant.md`](job-hub/multi-tenant.md).

## Why Hub, not git files

Live hunts need leases, heartbeats, and isolation. YAML-in-git cannot namespace tenants or survive a queue claim. Keep using git for playbooks (`skills/`). Use Hub APIs for jobs.

## Canonical store

```
Postgres (per account_id), or the in-memory store when DATABASE_URL is empty
  jobs, events, people, users, sessions, queue_items,
  skills, mcps, memory_items, messages, presence
Blob driver (memory, filesystem volume, or S3)
  candidate.yaml, resume, …
```

`GET /api/export/ledger` writes a YAML tarball when you need files. That snapshot is not dual-write.

## Write protocol

1. Authenticate (session cookie or `Authorization: Bearer`).
2. Dedup `GET /api/jobs`.
3. `POST` / `PATCH` only your lane’s fields.
4. Hub appends an event.
5. Queue work is tenant-routed; do not format routing keys at the call site.

## Optional live hunt board (maintainer-owned)

Maintainer runs the Go API and the React SPA ([`docs/runtime.md`](runtime.md)). First visit: `/login`.

## Secrets

Never commit `board/.env`, `board/tokens.local.json`, or resume PDFs. Passwords are Argon2 hashes in Postgres.
