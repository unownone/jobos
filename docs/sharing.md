# Sharing

Canonical state is **jobOS Hub**: Postgres + BlobStore + RabbitMQ, namespaced by account id. Git is the source repo for skills and docs, not the live job list.

Sign up at `/login` (username + password). No dashboard token. Each account only sees its own jobs, files, skills, memory, and queue traffic.

Hub operator/agent runbooks: [`docs/job-hub/human.md`](job-hub/human.md), [`docs/job-hub/agent.md`](job-hub/agent.md). Design: [`docs/job-hub/multi-tenant.md`](job-hub/multi-tenant.md).

## Why Hub, not git files

Live hunts need leases, heartbeats, and isolation. YAML-in-git cannot namespace tenants or survive a queue claim. Keep using git for playbooks (`skills/`). Use Hub APIs for jobs.

## Canonical store

```
Postgres (per account_id)
  jobs, events, people, users, sessions, queue_items,
  skills, mcps, memory_items, messages, presence
Filesystem BlobStore (volumized)
  {BLOB_ROOT}/{account_id}/candidate.yaml, resume, …
RabbitMQ
  exchange jobos.work, routing {account_id}.{kind}
```

`GET /api/export/ledger` writes a YAML tarball when you need files. That snapshot is not dual-write.

## Write protocol

1. Authenticate (session cookie or `Authorization: Bearer`).
2. Dedup `GET /api/jobs`.
3. `POST` / `PATCH` only your lane’s fields.
4. Hub appends an event.
5. Queue work is tenant-routed; do not format routing keys at the call site.

## Optional live hunt board (maintainer-owned)

Maintainer runs [`board/`](../board/README.md). Compose: Postgres + RabbitMQ + Hub + blob volume. First visit: `/` then `/login`.

## Secrets

Never commit `board/.env`, `board/tokens.local.json`, or resume PDFs. Passwords are Argon2 hashes in Postgres.
