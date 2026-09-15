# Install

See **[`docs/install.md`](docs/install.md)** for Docker, Docker Compose (plain and Traefik), `docker run`, uv/bare metal, TLS, backups, and the mandatory candidate onboarding step. Merge to `main` publishes a GHCR image and SSHs that tag onto this host: [`docs/deploy.md`](docs/deploy.md).

Quick start (plain Compose, port 8787):

```bash
docker compose -f docker-compose.plain.yml up -d --build
# Open the printed /admin/signup URL, then /onboarding. Do not skip it.
```
