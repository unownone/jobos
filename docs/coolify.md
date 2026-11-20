# Coolify: named volumes, no `${...}` in volume sources

Coolify parses Compose **before** Docker interpolates it. Its helper rejects volume *sources* that contain `${` (and other shell metacharacters) as a command-injection guard:

```text
Invalid Docker volume definition: Invalid volume source: contains forbidden character '${'
(variable substitution with potential command injection).
```

`${VAR}` in `environment:` is fine. `${VAR:-default}` in a **volume source** is not, including nested forms like `${JOBOS_PGDATA:-${HOME}/.jobos/pgdata}`.

Coolify also clones each deploy into a fresh `/artifacts/<id>` helper checkout. Host binds under `~` or that checkout **do not survive** the next deploy, so Postgres and RabbitMQ look “wiped.” Named Docker volumes live on the host engine and keep data across git deploys of the same Coolify resource.

## What this repo does

Committed Compose files use **named volumes** only for durable data:

| Volume | Container path | Service |
| --- | --- | --- |
| `pgdata` | `/var/lib/postgresql/data` | postgres |
| `rabbitmq` | `/var/lib/rabbitmq` | rabbitmq |
| `blobs` | `/var/lib/jobos/blobs` | hub |

Coolify prefixes those names with the resource UUID. The prefix is stable for that app, so continuous deployment does not create empty databases.

Do not put `JOBOS_PGDATA`, `JOBOS_BLOBS`, `JOBOS_AMQPDATA`, `$HOME`, or `~` on volume source lines. Env vars for passwords, `HUB_PUBLIC_URL`, and similar stay in `environment:` / Coolify’s Environment Variables tab.

## Postgres you already run

The Compose file still defines a bundled `postgres` service. Hub uses it when `DATABASE_URL` is unset.

To use a database Coolify (or another host) already runs, set secret `DATABASE_URL` to that server. Compose passes it through as `DATABASE_URL`. From inside the container, Postgres on the Docker host is `host.docker.internal`, not `127.0.0.1`. Add `sslmode` to the URL when the server requires TLS.

`JOBOS_PG_PASSWORD` (and `JOBOS_PG_USER`, `JOBOS_PG_HOST`, `JOBOS_PG_PORT`, `JOBOS_PG_DB`) still apply only when `DATABASE_URL` is unset.

`docker compose down` keeps named volumes. `docker compose down -v` (or deleting the Coolify resource) deletes them.

## Deploy on Coolify

1. New **Docker Compose** resource → GitHub `unownone/jobos` → branch `main`.
2. Compose file: `docker-compose.yml` (Hub on 8787, internal Postgres + RabbitMQ). Same stack as local Compose.
3. Set `HUB_PUBLIC_URL` and usually `HUB_PUBLIC_HOST` to the Coolify FQDN (`https://hub.example.com`).
4. Confirm Persistent Storage shows the three named volumes (read-only; owned by Compose). Do not convert them to bind mounts with `${` or `~`.
5. After first boot: `/login` (or `/admin/signup` on an empty database) then `/onboarding`. Probe `GET /health` on 8787.
6. Redeploy on every push to `main`. Named volumes are not recreated.

If a previous deploy already failed on `${` in volume sources, Coolify may have stored a broken Persistent Storage row (it then errors even after git is fixed). Remove those storage entries or recreate the Compose resource so it reparses this file, then deploy again.

## Migrating from `~/.jobos/...` binds

If an older host already has data in `~/.jobos/pgdata` (or blobs/rabbitmq), copy it into the named volumes **once** after the first compose create, with Postgres/RabbitMQ stopped:

```bash
# volume names are <compose-project>_pgdata (local default: jobos_pgdata)
docker compose stop postgres rabbitmq hub
docker run --rm -v jobos_pgdata:/to -v "$HOME/.jobos/pgdata":/from alpine \
  sh -c 'cd /from && cp -a . /to/'
docker run --rm -v jobos_rabbitmq:/to -v "$HOME/.jobos/rabbitmq":/from alpine \
  sh -c 'cd /from && cp -a . /to/'
docker run --rm -v jobos_blobs:/to -v "$HOME/.jobos/blobs":/from alpine \
  sh -c 'cd /from && cp -a . /to/'
docker compose up -d
```

On Coolify, use the prefixed names from Persistent Storage / `docker volume ls` instead of `jobos_pgdata`.

## Related

- Install overview: [`install.md`](install.md)
- This repo’s push-to-main host: [`deploy.md`](deploy.md)
