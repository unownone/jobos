# Deploy Job Hub from GitHub Releases

GitHub is the source of truth (`https://github.com/unownone/jobos`). A merge to `main` does **not** copy this git tree onto the OCI box.

```
merge to main
  → Release workflow (ubuntu-24.04 + ubuntu-24.04-arm)
      build linux/amd64 + linux/arm64
      push ghcr.io/unownone/jobos:<tag>
      create GitHub Release vYYYY.MM.DD-<sha7>
  → Deploy workflow (ubuntu-latest)
      SSH as opc@the-box
      copy compose.yml + traefik/ only
      docker pull ghcr.io/unownone/jobos:<tag>
      docker compose up -d
```

Live Hub origin on this hunt: `http://129.225.116.58/` (also `:80` / `:443` via Traefik, and `:8787`).

SQLite and secrets stay on Docker volume `jobos_hub-data` (`/data` in the container). Deploys do **not** use `--volumes`. The compose project name stays `jobos`.

## What runs

| Piece | When | What |
| --- | --- | --- |
| [`.github/workflows/deploy-check.yml`](../.github/workflows/deploy-check.yml) | **Pull request** | GitHub-hosted: offline wiring selftest + amd64 image smoke. Does **not** deploy. |
| [`.github/workflows/release.yml`](../.github/workflows/release.yml) | **Push to `main`** | GitHub-hosted: tag, multi-arch GHCR push, GitHub Release |
| [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) | **Release published** or **Actions → Deploy → Run workflow** | GitHub-hosted: SSH into the box, pull that GHCR tag, apply compose |
| [`scripts/hub_apply_image.sh`](../scripts/hub_apply_image.sh) | On the box (called over SSH) | `docker compose pull` + `up -d` + wait for `GET /health` |

No self-hosted Actions runner. No `git pull` on the box. Feature branches never auto-deploy.

## Secrets and variables you must set

The first Deploy run will **fail on purpose** until these exist. Add them at
[repo Settings → Secrets and variables → Actions](https://github.com/unownone/jobos/settings/secrets/actions).

### GitHub Actions secrets

| Name | Required | What to paste |
| --- | --- | --- |
| `JOBOS_HOST_SSH_KEY` | **Yes** | Private OpenSSH key that can log in as `opc` on the Hub VM. Public half goes in `/home/opc/.ssh/authorized_keys`. |
| `JOBOS_HOST_KNOWN_HOSTS` | Recommended | Output of `ssh-keyscan -H 129.225.116.58` (pins the host key). If unset, Deploy falls back to TOFU `ssh-keyscan`. |
| `JOBOS_DEPLOY_KEY` | Fallback only | Used **only** if `JOBOS_HOST_SSH_KEY` is empty. That secret was the GitHub *repo* deploy key; reuse it here only if the same private key is also authorized on the box. |

`GITHUB_TOKEN` is created by Actions. Release uses it to push GHCR. Deploy passes it over SSH for a one-shot `docker login ghcr.io` (the repo is private, so the image is not public). It is not written to disk on the box.

### GitHub Actions variables

| Name | Required | Example |
| --- | --- | --- |
| `JOBOS_HOST` | **Yes** | `129.225.116.58` |
| `JOBOS_HOST_USER` | No (default `opc`) | `opc` |
| `JOBOS_HOST_SSH_PORT` | No (default `22`) | `22` |
| `JOBOS_DEPLOY_DIR` | No (default `/home/opc/jobos`) | `/home/opc/jobos` |

### GitHub repo settings (not secrets)

1. **Actions → General → Workflow permissions:** Read and write. Needed so Release can create tags/releases and push GHCR (`permissions:` in the workflow is not enough if the org forces read-only).
2. **Packages:** after the first Release, confirm `ghcr.io/unownone/jobos` exists and is linked to this repo. Leave it private.

### On the OCI box (once)

```bash
# 1. Public key matching JOBOS_HOST_SSH_KEY
mkdir -p ~/.ssh && chmod 700 ~/.ssh
# append the .pub line to ~/.ssh/authorized_keys (mode 600)

# 2. Inbound SSH from GitHub-hosted runners (security list / iptables).
#    GitHub-hosted IPs are not a small allowlist. Open TCP 22 to 0.0.0.0/0
#    or to GitHub's published Actions ranges, or the SSH step cannot connect.

# 3. Public origin for invite URLs (already typical on this hunt)
cat > ~/.jobos/deploy.env <<'EOF'
JOBOS_DEPLOY_DIR=/home/opc/jobos
HUB_PUBLIC_HOST=129.225.116.58
HUB_PUBLIC_URL=http://129.225.116.58
EOF
chmod 600 ~/.jobos/deploy.env

# 4. Stop the retired self-hosted runner + git watcher so they cannot
#    docker compose build from a leftover clone and overwrite GHCR applies.
bash scripts/disable_legacy_selfhosted_deploy.sh
# or: sudo systemctl disable --now jobos-github-runner.service
#     sudo systemctl disable --now jobos-deploy-watch.timer

# 5. Docker Engine + Compose v2 (already installed on this hunt).
#    Optional bootstrap of compose.yml + traefik into ~/jobos:
#    bash scripts/install_host_services.sh
```

Do not put Hub tokens, bootstrap URLs, `board/.env`, or private keys in git or in workflow YAML.

## Tags

Every merge to `main` mints `vYYYY.MM.DD-<sha7>` (UTC date + first 7 chars of the commit). Example: `v2026.09.15-a1b2c3d`.

That string is:

- the Git tag and GitHub Release name
- the GHCR tag (`ghcr.io/unownone/jobos:v2026.09.15-a1b2c3d`)
- what Deploy SSHs and `docker pull`s

`latest` and `sha-<sha7>` are also published. Production always pins the release tag.

## One-time image apply (on the box)

After compose files exist in `$JOBOS_DEPLOY_DIR` and you can `docker login ghcr.io`:

```bash
bash scripts/hub_apply_image.sh v2026.09.15-a1b2c3d
# or: make deploy   # uses JOBOS_IMAGE or :latest
```

## Buttons and badges

- **CI** — lint, unit, e2e on GitHub-hosted Ubuntu
- **Deploy check** — wiring + image smoke on every PR
- **Release** — GHCR + GitHub Release on push to `main`
- **Deploy** — SSH apply on release (or the Actions **Run workflow** button with a tag)

Merge to `main` only after **CI** and **Deploy check** are green on the PR.

## Native work after deploy

| Path | Role |
| --- | --- |
| `/home/opc/jobos` | Compose + traefik only (no git tree) |
| `/home/opc/jobOS` | Native git checkout for agents / humans |
| `http://127.0.0.1:8787/health` | Local health |
| `http://129.225.116.58/` | Public Hub (Traefik) |
| `ghcr.io/unownone/jobos:<tag>` | What production is running |

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Deploy fails “Host SSH key secret is not set” | Add `JOBOS_HOST_SSH_KEY` (and `JOBOS_HOST`) |
| `Permission denied (publickey)` | Public key missing from `authorized_keys`, or you stored the GitHub *repo* deploy key which is not authorized on the box |
| SSH times out | Ingress: TCP 22 closed to GitHub-hosted runners |
| `denied: requested access to the resource is denied` on pull | GHCR package private; Deploy must run with `packages: read`. Re-run the Deploy workflow. |
| Health failing after compose | `sudo docker compose -f /home/opc/jobos/compose.yml logs --tail 80 hub` |
| Stack rebuilt from source unexpectedly | Old watcher still on: `systemctl is-enabled jobos-deploy-watch.timer` |
| Invites point at 127.0.0.1 | Set `HUB_PUBLIC_URL` in `~/.jobos/deploy.env` and re-run Deploy |
