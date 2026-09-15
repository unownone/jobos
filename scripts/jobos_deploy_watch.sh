#!/usr/bin/env bash
# Poll GitHub origin/main and deploy when the SHA changes.
# Outbound-only (git fetch). No inbound webhook. Complements the Actions runner.
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

if [[ -f "${HOME}/.jobos/deploy.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "${HOME}/.jobos/deploy.env"
  set +a
fi

jobos_load_github_ssh

REPO="${JOBOS_REPO:-${HOME}/jobos-live}"
STATE_DIR="${JOBOS_STATE_DIR:-${HOME}/.jobos}"
SCRIPT="${JOBOS_DEPLOY_SCRIPT:-$REPO/scripts/hub_host_deploy.sh}"
mkdir -p "$STATE_DIR"

if [[ ! -d "$REPO/.git" ]]; then
  echo "jobos-deploy-watch: $REPO is not a git clone" >&2
  exit 1
fi

cd "$REPO"
git fetch origin --prune --tags
want="$(git rev-parse origin/main)"
have=""
if [[ -f "$STATE_DIR/deployed.sha" ]]; then
  have="$(tr -d '[:space:]' < "$STATE_DIR/deployed.sha")"
fi
if [[ "$want" == "$have" ]]; then
  echo "jobos-deploy-watch: already on $want"
  exit 0
fi

echo "jobos-deploy-watch: $have -> $want"
if [[ -x "$SCRIPT" ]]; then
  exec bash "$SCRIPT" "$want"
fi
# Until main contains hub_host_deploy.sh, deploy with compose from this clone.
git reset --hard "$want"
docker_cmd() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
    return
  fi
  sudo -n docker "$@"
}
docker_cmd compose -f "${JOBOS_COMPOSE_FILE:-docker-compose.yml}" up -d --build
echo "$want" > "$STATE_DIR/deployed.sha"
