# Deploy Job Hub on push to `main`

GitHub is the source of truth (`git@github.com:unownone/jobos.git`). This OCI host deploys **Job Hub** whenever `main` moves.

Live Hub origin on this box: `http://129.225.116.58/` (also `:80` / `:443` via Traefik, and `:8787`).

Git fetch/push uses **SSH on port 443** (`ssh.github.com`) with the repo deploy key at `~/.ssh/jobos_deploy`. Port 22 to `github.com` is often filtered.

## What runs

| Piece | When | What |
| --- | --- | --- |
| [`.github/workflows/deploy-check.yml`](../.github/workflows/deploy-check.yml) | **Pull request** (or **Run workflow**) | GitHub-hosted: offline SSH wiring selftest, then optional live `git ls-remote` if secret `JOBOS_DEPLOY_KEY` is set. Does **not** deploy. |
| [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) | **Push to `main`** or **Actions → Deploy → Run workflow** | Self-hosted runner labeled `jobos` pulls the SHA into `/home/opc/jobos-live` and `docker compose up -d --build` |
| `jobos-deploy-watch.timer` | Every ~45s | Outbound `git fetch origin/main` over SSH/443; deploys if the SHA changed (works even before the runner is registered) |
| [`scripts/hub_host_deploy.sh`](../scripts/hub_host_deploy.sh) | Called by both | SSH setup, fetch, rebuild, wait for `GET /health` |

The agent working tree (`/home/opc/jobOS`) is **not** reset. Only the live clone is.

```
GitHub PR ──► Actions (ubuntu-latest) ──► deploy-check (no ship)
GitHub main ──push──► Actions (runner: jobos)
                 └──git fetch (ssh.github.com:443)──► /home/opc/jobos-live ──compose──► Traefik + Hub
```

SQLite and Hub Docker volumes are gone. Durable state is PostgreSQL. Postgres files stay on the host bind `JOBOS_PGDATA` (default `~/.jobos/pgdata`). The Hub container has **no** volume. Deploys do **not** publish Postgres ports.

## Deploy keys (SSH)

After rotating GitHub deploy keys:

1. Put the **private** key on the host as `~/.ssh/jobos_deploy` (mode 600). The matching **public** key is the GitHub deploy key (`Settings → Deploy keys`). Read-only is enough for host fetch. Enable **Allow write access** only if this box must `git push` over SSH.
2. Install SSH-over-443 config (idempotent):

```bash
bash scripts/install_github_ssh.sh --key-file /path/to/jobos_deploy
# or: cat jobos_deploy | bash scripts/install_github_ssh.sh --key-stdin
```

3. Optional: store the same private key as Actions secret `JOBOS_DEPLOY_KEY` so the PR workflow can `git ls-remote` over SSH. Do not commit the key.

Pinned host keys live in [`deploy/ssh/known_hosts`](../deploy/ssh/known_hosts) (GitHub’s published fingerprints). Runtime config is `~/.jobos/ssh/config`.

Prove fetch without deploying:

```bash
make deploy-check
# live probe when the key is in place:
JOBOS_SSH_LIVE=1 bash scripts/github_ssh_selftest.sh
```

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

# 3. GitHub SSH over 443 + deploy key
bash scripts/install_github_ssh.sh --key-file ~/.ssh/jobos_deploy

# 4. Watcher + (optional) runner units
bash scripts/install_host_services.sh

# 5. Self-hosted Actions runner (so the Deploy workflow actually runs)
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
- Deploy check — SSH wiring on every PR
- Deploy — this host, on push to `main`

`workflow_dispatch` is the **Deploy** button in the Actions tab.

## Native work after deploy

| Path | Role |
| --- | --- |
| `/home/opc/jobos-live` | What production is running (`main` only) |
| `/home/opc/jobOS` | Native git checkout for agents / humans |
| `http://127.0.0.1:8787/health` | Local health |
| `http://129.225.116.58/` | Public Hub (Traefik) |

Feature branches never auto-deploy. Merge (or push) to `main` only after **Deploy check** is green on the PR.

## Secrets

Do not put Hub tokens, bootstrap URLs, `board/.env`, or deploy **private** keys in git or in workflow YAML. Host env is `~/.jobos/deploy.env` (mode 600) plus Postgres under `~/.jobos/pgdata`. The SSH private key is `~/.ssh/jobos_deploy`. Optional Actions secret: `JOBOS_DEPLOY_KEY`.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Deploy job queued forever | Runner not online: `systemctl status jobos-github-runner`. The timer still deploys. |
| `git fetch` hangs or times out | Port 22 is blocked. Re-run `bash scripts/install_github_ssh.sh` so git uses `ssh.github.com:443`. |
| `Permission denied (publickey)` | Deploy key rotated: install the new private key at `~/.ssh/jobos_deploy` and confirm the public half is on the repo. |
| Health failing after compose | `sudo docker compose -f /home/opc/jobos-live/docker-compose.yml logs --tail 80 hub` |
| Invites point at 127.0.0.1 | Set `HUB_PUBLIC_URL` in `~/.jobos/deploy.env` and the live clone `.env`, then redeploy |
| Watcher no-op | `cat ~/.jobos/deployed.sha` vs `git -C /home/opc/jobos-live rev-parse origin/main` |
