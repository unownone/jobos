# board/

Local Hub secrets and a thin start wrapper. The Hub itself is **Go** (`server/`) plus the React SPA (`web/`).

| Path | Role |
| --- | --- |
| `start.sh` | Interactive public-host prompt, then `scripts/hub_deploy.sh` |
| `.env` / `tokens.local.json` | Gitignored secrets (role tokens, bootstrap). Minted on first start |
| `docker-compose.yml` | Legacy single-`hub` Compose (same as repo-root `docker-compose.yml`) |
| `data/` | Local scratch (sqlite path leftovers); Postgres is the real store |

```bash
# from repo root
bash board/start.sh
# or
docker compose up -d --build
```

Operator docs: [`docs/runtime.md`](../docs/runtime.md), [`docs/install.md`](../docs/install.md), [`docs/job-hub/human.md`](../docs/job-hub/human.md).
