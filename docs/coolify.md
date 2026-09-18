# Coolify: volume sources cannot use `${...}`

Coolify parses Compose **before** Docker interpolates it. Its helper rejects volume *sources* that contain `${` (and other shell metacharacters) as a command-injection guard. Deploy then fails with:

```text
Invalid Docker volume definition: Invalid volume source: contains forbidden character '${'
(variable substitution with potential command injection).
```

`${VAR}` in `environment:` is fine. `${VAR:-default}` in a **volume source** is not, including nested forms like `${JOBOS_PGDATA:-${HOME}/.jobos/pgdata}`.

## What this repo does

Committed Compose files use **literal host binds** only:

| Host path | Container | Service |
| --- | --- | --- |
| `~/.jobos/pgdata` | `/var/lib/postgresql/data` | postgres |
| `~/.jobos/rabbitmq` | `/var/lib/rabbitmq` | rabbitmq |
| `~/.jobos/blobs` | `/var/lib/jobos/blobs` | hub |

Do not add `JOBOS_PGDATA`, `JOBOS_BLOBS`, or `JOBOS_AMQPDATA` interpolation back onto those lines. Env vars for passwords, `HUB_PUBLIC_URL`, and similar stay in `environment:` / `.env`.

## Deploy on Coolify

1. New **Docker Compose** resource → GitHub `unownone/jobos` → branch `main`.
2. Compose file: `docker-compose.yml` (Hub on 8787, internal Postgres + RabbitMQ). Same stack as local Compose.
3. Set `HUB_PUBLIC_URL` and usually `HUB_PUBLIC_HOST` to the Coolify FQDN (`https://hub.example.com`).
4. Persist the three binds above (Coolify Persistent Storage). There is no `hub-data` SQLite volume anymore.
5. After first boot: `/login` (or `/admin/signup` on an empty database) then `/onboarding`. Probe `GET /health` on 8787.

## Custom data directories

If you need a path other than `~/.jobos/...`, use a **local** override with a literal absolute path — not Compose `${VAR:-...}` in the committed file:

```yaml
# docker-compose.override.yml  (gitignored; do not commit)
services:
  postgres:
    volumes:
      - /var/lib/jobos/pgdata:/var/lib/postgresql/data
```

On Coolify, change the mount in Persistent Storage to a safe absolute path with no `$`, backticks, or `;`.

## Related

- Install overview: [`install.md`](install.md)
- This repo’s push-to-main host: [`deploy.md`](deploy.md)
