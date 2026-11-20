#!/usr/bin/env bash
# Deploy Job Hub on this host from GitHub main (or a pinned SHA).
# Intended for the live clone at $JOBOS_REPO (default: $HOME/jobos-live),
# not the agent's working tree. Durable data is named Docker volumes
# (pgdata, blobs). Coolify forbids ${...} in volume sources and
# would wipe ~/ binds on each helper checkout. See docs/coolify.md.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
jobos_load_github_ssh() {
  if [[ -f "$SCRIPT_DIR/github_ssh.sh" ]]; then
    # shellcheck source=github_ssh.sh
    source "$SCRIPT_DIR/github_ssh.sh"
  elif [[ -f "${HOME}/.jobos/github_ssh.sh" ]]; then
    # shellcheck source=/dev/null
    source "${HOME}/.jobos/github_ssh.sh"
  fi
  if declare -F jobos_github_ssh_apply >/dev/null; then
    jobos_github_ssh_apply
  fi
}

usage() {
  cat <<'EOF'
Usage: hub_host_deploy.sh [--skip-git] [sha]

Pull origin/main (or reset to sha), rebuild Compose, wait for /health.

  --skip-git   Do not fetch; deploy the working tree as-is.
  sha          Optional 40-char commit to deploy instead of origin/main.

Env (optional file: $HOME/.jobos/deploy.env):
  JOBOS_REPO            Live clone (default: $HOME/jobos-live)
  JOBOS_COMPOSE_FILE    Compose file (default: docker-compose.yml)
  HUB_PUBLIC_HOST       Hostname, IP, or IP:port for invite URLs
  HUB_PUBLIC_URL        Full origin (wins over HUB_PUBLIC_HOST)
  JOBOS_PG_PASSWORD    Postgres password (default: jobos). Not published; Hub-only.
                       Used when DATABASE_URL is unset (bundled service).
  DATABASE_URL         Outside Postgres. Secret / repo-root .env. Wins over the bundled URL.
                       Durable data is named volumes pgdata and blobs.
EOF
}

SKIP_GIT=0
SHA=""
for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
    --skip-git) SKIP_GIT=1 ;;
    *) SHA="$arg" ;;
  esac
done

if [[ -f "${HOME}/.jobos/deploy.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "${HOME}/.jobos/deploy.env"
  set +a
fi

jobos_load_github_ssh

REPO="${JOBOS_REPO:-${HOME}/jobos-live}"
COMPOSE_FILE="${JOBOS_COMPOSE_FILE:-docker-compose.yml}"
HEALTH_URL="${JOBOS_HEALTH_URL:-http://127.0.0.1:8080/health}"
STATE_DIR="${JOBOS_STATE_DIR:-${HOME}/.jobos}"
mkdir -p "$STATE_DIR"

if [[ ! -d "$REPO/.git" ]]; then
  echo "hub_host_deploy: $REPO is not a git clone" >&2
  exit 1
fi

cd "$REPO"

if [[ "$SKIP_GIT" != "1" ]]; then
  git fetch origin --prune --tags
  if [[ -n "$SHA" ]]; then
    git reset --hard "$SHA"
  else
    git checkout -B main origin/main
    git reset --hard origin/main
  fi
fi

DEPLOYED_SHA="$(git rev-parse HEAD)"
DEPLOYED_SHORT="$(git rev-parse --short HEAD)"
echo "Job Hub host deploy"
echo "  repo: $REPO"
echo "  sha:  $DEPLOYED_SHA"
echo "  compose: $COMPOSE_FILE"
echo "  postgres volume: pgdata (compose project named volume)"
if [[ -n "${HUB_PUBLIC_URL:-}" ]]; then
  echo "  public: $HUB_PUBLIC_URL"
elif [[ -n "${HUB_PUBLIC_HOST:-}" ]]; then
  echo "  public host: $HUB_PUBLIC_HOST"
fi

if [[ -n "${HUB_PUBLIC_HOST:-}" || -n "${HUB_PUBLIC_URL:-}" ]]; then
  python3 - "$REPO/.env" "${HUB_PUBLIC_HOST:-}" "${HUB_PUBLIC_URL:-}" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
host, url = sys.argv[2], sys.argv[3]
existing = {}
if path.is_file():
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        existing[k.strip()] = v.strip()
if host:
    existing["HUB_PUBLIC_HOST"] = host
if url:
    existing["HUB_PUBLIC_URL"] = url.rstrip("/")
lines = [f"{k}={v}" for k, v in existing.items() if v]
path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
PY
  chmod 600 "$REPO/.env" 2>/dev/null || true
fi

docker_cmd() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
    return
  fi
  sudo -n docker "$@"
}

docker_cmd compose -f "$COMPOSE_FILE" up -d --build

ok=0
for _ in $(seq 1 36); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 5
done
if [[ "$ok" != "1" ]]; then
  echo "hub_host_deploy: health check failed at $HEALTH_URL" >&2
  docker_cmd compose -f "$COMPOSE_FILE" ps >&2 || true
  docker_cmd compose -f "$COMPOSE_FILE" logs --tail 80 hub >&2 || true
  exit 1
fi

echo "$DEPLOYED_SHA" > "$STATE_DIR/deployed.sha"
curl -sS "$HEALTH_URL"
echo
echo "deployed $DEPLOYED_SHORT"
