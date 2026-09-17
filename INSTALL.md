# Install

See **[`docs/install.md`](docs/install.md)** for Docker, Docker Compose (Hub on 8787, optional Traefik), `docker run`, uv/bare metal, TLS, backups, and the mandatory candidate onboarding step. This GitHub repo’s OCI host deploys on push to `main`: [`docs/deploy.md`](docs/deploy.md).

Quick start (Hub Compose, port 8787):

```bash
docker compose up -d --build
# Open the printed /admin/signup URL, then /onboarding. Do not skip it.
curl -sS http://127.0.0.1:8787/llms.txt
```
