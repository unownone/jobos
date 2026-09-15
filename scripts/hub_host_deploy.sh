#!/usr/bin/env bash
# Manual on-host apply of a GHCR Job Hub image (same as the Actions SSH path).
# The git clone is not used. Prefer: GitHub Release → Deploy workflow.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: hub_host_deploy.sh [--skip-git] [tag-or-image]

Pull a GHCR tag and recreate Compose. Volume jobos_hub-data is kept.

  --skip-git   Ignored (legacy). This path never git-pulls.
  tag          Release tag (vYYYY.MM.DD-<sha7>) or full image ref.
               Default: $JOBOS_IMAGE or :latest

Env (optional file: $HOME/.jobos/deploy.env):
  JOBOS_DEPLOY_DIR      Compose dir (default: $HOME/jobos)
  JOBOS_GHCR_IMAGE      Image name without tag (default: ghcr.io/unownone/jobos)
  HUB_PUBLIC_HOST / HUB_PUBLIC_URL
  JOBOS_HEALTH_URL
EOF
}

SKIP_GIT=0
REF=""
for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
    --skip-git) SKIP_GIT=1 ;;
    *) REF="$arg" ;;
  esac
done

if [[ "$SKIP_GIT" == "1" ]]; then
  echo "hub_host_deploy: --skip-git is a no-op; deploys no longer copy git."
fi

if [[ -f "${HOME}/.jobos/deploy.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "${HOME}/.jobos/deploy.env"
  set +a
fi

if [[ -z "$REF" ]]; then
  REF="${JOBOS_IMAGE:-}"
fi
if [[ -z "$REF" ]]; then
  REF="${JOBOS_GHCR_IMAGE:-ghcr.io/unownone/jobos}:latest"
fi

exec bash "$SCRIPT_DIR/hub_apply_image.sh" "$REF"
