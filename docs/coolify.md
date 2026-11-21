# Coolify: named volumes, no `${...}` in volume sources

Coolify parses Compose **before** Docker interpolates it. Its helper rejects volume *sources* that contain `${` (and other shell metacharacters) as a command-injection guard:

```text
Invalid Docker volume definition: Invalid volume source: contains forbidden character '${'
(variable substitution with potential command injection).
```

`${VAR}` in `environment:` is fine. `${VAR:-default}` in a **volume source** is not, including nested forms like `${JOBOS_PGDATA:-${HOME}/.jobos/pgdata}`.

Coolify also clones each deploy into a fresh `/artifacts/<id>` helper checkout. Host binds under `~` or that checkout **do not survive** the next deploy, so Postgres looks wiped. Named Docker volumes live on the host engine and keep data across git deploys of the same Coolify resource.

## What this repo does

Production Coolify/host deploys use the **legacy single-container** Compose file [`docker-compose.yml`](../docker-compose.yml):

| Service | Port | Notes |
| --- | --- | --- |
| `hub` | **8787** | Root [`Dockerfile`](../Dockerfile): Go API + built React SPA |
| `postgres` | internal | Named volume `pgdata` |

| Volume | Container path | Service |
| --- | --- | --- |
| `pgdata` | `/var/lib/postgresql/data` | postgres |
| `blobs` | `/var/lib/jobos/blobs` | hub |

RabbitMQ is not in `docker-compose.yml`. Queue leases are Postgres rows. Redis / MinIO are optional (see `docker-compose.split.yml` profiles) and are not required for Coolify.

The SPA is **not** a separate nginx container in this layout. `HUB_WEB_ROOT=/opt/jobos/web` must stay set (Compose and the image both set it). Without it, `/` returns Gin’s bare `404 page not found`.

Coolify prefixes volume names with the resource UUID. The prefix is stable for that app, so continuous deployment does not create empty databases.

Do not put `JOBOS_PGDATA`, `JOBOS_BLOBS`, `$HOME`, or `~` on volume source lines. Env vars for passwords, `HUB_PUBLIC_URL`, and similar stay in `environment:` / Coolify’s Environment Variables tab.

## Postgres you already run

The Compose file defines a bundled `postgres` service. With `HUB_PLUGINS=auto`, the API fills `DATABASE_URL` when that hostname resolves. An explicit `DATABASE_URL` wins.

To use a database Coolify (or another host) already runs, set secret `DATABASE_URL` to that server. Compose passes it through as `DATABASE_URL`. From inside the container, Postgres on the Docker host is `host.docker.internal`, not `127.0.0.1`. Add `sslmode` to the URL when the server requires TLS.

`JOBOS_PG_PASSWORD` (and `JOBOS_PG_USER`, `JOBOS_PG_HOST`, `JOBOS_PG_PORT`, `JOBOS_PG_DB`) apply when the API fills `DATABASE_URL` from the bundled Postgres.

`docker compose down` keeps named volumes. `docker compose down -v` (or deleting the Coolify resource) deletes them.

## Deploy on Coolify

1. New **Docker Compose** resource → GitHub `unownone/jobos` → branch `main`.
2. Compose file: `docker-compose.yml` (single `hub` on **8787** + Postgres). Do **not** point Coolify at `docker-compose.split.yml` unless you intentionally want separate `api`/`web` services.
3. Set `HUB_PUBLIC_URL` (and usually `HUB_PUBLIC_HOST`) to the Coolify FQDN (`https://jobs.example.com`).
4. Confirm Persistent Storage shows `pgdata` and `blobs`. Do not convert them to bind mounts with `${` or `~`.
5. After first boot: `/login`, then `/onboarding`. Probe `GET /health` on port **8787**.
6. If Coolify is configured as a **Dockerfile** app instead of Compose, keep the public port on **8787** (image default `BOARD_PORT=8787`). Railway/Render may inject `PORT`; that wins over `BOARD_PORT`. A Dockerfile-only deploy does **not** include the Compose Postgres service — set secret `DATABASE_URL` to an external Postgres, and set durable blobs (`BLOB_ADAPTER=filesystem` + a persistent `BLOB_ROOT`, or S3/`BLOB_DRIVER=s3`). Leaving those unset uses in-memory defaults that are wiped on restart.
7. Redeploy on every push to `main`. Named volumes are not recreated.

If a previous deploy already failed on `${` in volume sources, Coolify may have stored a broken Persistent Storage row (it then errors even after git is fixed). Remove those storage entries or recreate the Compose resource so it reparses this file, then deploy again.

## Migrating from `~/.jobos/...` binds

If an older host already has data in `~/.jobos/pgdata` or `~/.jobos/blobs`, copy it into the named volumes **once**. The bundled `postgres` service may initialize `pgdata` on first `compose up`, so **stop Postgres and ensure the target volume is empty** before copying (or preserve/rename any existing volume you care about before replacing it):

```bash
# volume names are <compose-project>_pgdata (local default: jobos_pgdata)
docker compose stop postgres hub
# empty target if Postgres already initialized it (backs up nothing — rename the volume first if unsure)
docker run --rm -v jobos_pgdata:/to alpine sh -c 'rm -rf /to/* /to/.[!.]*'
docker run --rm -v jobos_pgdata:/to -v "$HOME/.jobos/pgdata":/from alpine \
  sh -c 'cd /from && cp -a . /to/'
docker run --rm -v jobos_blobs:/to alpine sh -c 'rm -rf /to/* /to/.[!.]*'
docker run --rm -v jobos_blobs:/to -v "$HOME/.jobos/blobs":/from alpine \
  sh -c 'cd /from && cp -a . /to/'
docker compose up -d
```

On Coolify, use the prefixed names from Persistent Storage / `docker volume ls` instead of `jobos_pgdata`.

## Related

- Install overview: [`install.md`](install.md)
- This repo’s push-to-main host: [`deploy.md`](deploy.md)
