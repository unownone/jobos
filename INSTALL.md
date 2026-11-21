# Install

See **[`docs/install.md`](docs/install.md)** and **[`docs/runtime.md`](docs/runtime.md)**. Default Compose is a Go API and a React SPA. Postgres, Redis, and MinIO are optional profiles. This GitHub repo’s OCI host deploys on push to `main`: [`docs/deploy.md`](docs/deploy.md).

Quick start (SPA on 8080, API on 8081):

```bash
docker compose up -d --build
# Open http://127.0.0.1:8080/login, then /onboarding. Do not skip it.
curl -sS http://127.0.0.1:8080/llms.txt
```
