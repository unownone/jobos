# Deploy Job Hub on push to `main`

GitHub is the source of truth (`git@github.com:unownone/jobos.git`). This OCI host deploys **Job Hub** whenever `main` moves.

Live Hub origin on this box: `http://129.225.116.58/` (also `:80` / `:443` via Traefik, and `:8787`).

## What runs

| Piece | When | What |
| --- | --- | --- |
| [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) | **Push to `main`** or **Actions → Deploy → Run workflow** | Self-hosted runner labeled `jobos` pulls the SHA into `/home/opc/jobos-live` and `docker compose up -d --build` |
| `jobos-deploy-watch.timer` | Every ~45s | Outbound `git fetch origin/main`; deploys if the SHA changed (works even before the runner is registered) |
| [`scripts/hub_host_deploy.sh`](../scripts/hub_host_deploy.sh) | Called by both | Fetch, rebuild, wait for `GET /health` |

The agent working tree (`/home/opc/jobOS`) is **not** reset. Only the live clone is.

```
GitHub main ──push──► Actions (runner: jobos)
                 └──git fetch──► /home/opc/jobos-live ──compose──► Traefik + Hub
```

SQLite and secrets stay on Docker volume `jobos_hub-data` (`/data` in the container). Deploys do **not** use `--volumes`.

## One-time host setup

On this machine (already done for the current box):

```bash
# 1. Live clone (separate from any feature-branch checkout)
git clone --branch main git@github.com:unownone/jobos.git /home/opc/jobos-live

# 2. Public origin for invite / signup URLs
cat > ~/.jobos/deploy.env <<'EOF'
JOBOS_REPO=/home/opc/jobos-live
HUB_PUBLIC_HOST=129.225.116.58
HUB_PUBLIC_URL=http://129.225.116.58
EOF

# 3. Watcher + (optional) runner units
bash scripts/install_host_services.sh

# 4. Self-hosted Actions runner (so the Deploy workflow actually runs)
gh auth login   # or paste a token from GitHub → Settings → Actions → Runners
bash scripts/install_github_runner.sh
sudo systemctl enable --now jobos-github-runner.service
```

GitHub runner registration: [repo Settings → Actions → Runners → New self-hosted runner](https://github.com/unownone/jobos/settings/actions/runners/new). Labels must include `jobos`.

Manual deploy of whatever `origin/main` is right now:

```bash
bash scripts/hub_host_deploy.sh
# or: make deploy
```

## Buttons and badges

The README badges hit these workflows:

- CI — lint, unit, e2e on GitHub-hosted Ubuntu
- Deploy — this host, on push to `main`

`workflow_dispatch` is the **Deploy** button in the Actions tab.

## Native work after deploy

| Path | Role |
| --- | --- |
| `/home/opc/jobos-live` | What production is running (`main` only) |
| `/home/opc/jobOS` | Native git checkout for agents / humans |
| `http://127.0.0.1:8787/health` | Local health |
| `http://129.225.116.58/` | Public Hub (Traefik) |

Feature branches never auto-deploy. Merge (or push) to `main`.

## Secrets

Do not put Hub tokens, bootstrap URLs, or `board/.env` in git or in workflow YAML. Host env is `~/.jobos/deploy.env` (mode 600) plus the Docker volume.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Deploy job queued forever | Runner not online: `systemctl status jobos-github-runner`. The timer still deploys. |
| Health failing after compose | `sudo docker compose -f /home/opc/jobos-live/docker-compose.yml logs --tail 80 hub` |
| Invites point at 127.0.0.1 | Set `HUB_PUBLIC_URL` in `~/.jobos/deploy.env` and the live clone `.env`, then redeploy |
| Watcher no-op | `cat ~/.jobos/deployed.sha` vs `git -C /home/opc/jobos-live rev-parse origin/main` |
