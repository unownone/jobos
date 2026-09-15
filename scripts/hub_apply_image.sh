#!/usr/bin/env bash
# Apply a GHCR Job Hub image on this host. Does not clone or copy the git tree.
# Expected cwd layout (synced by hub_remote_deploy.sh):
#   compose.yml  traefik/traefik.yml  traefik/dynamic.yml
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: hub_apply_image.sh <tag-or-image>

Pull ghcr.io/<owner>/jobos:<tag> (or a full image ref) and recreate the
Job Hub stack. Docker volume jobos_hub-data is kept.

  v2026.09.15-abc1234
  ghcr.io/unownone/jobos:v2026.09.15-abc1234

Env (optional file: $HOME/.jobos/deploy.env):
  JOBOS_DEPLOY_DIR      Compose dir (default: $HOME/jobos)
  JOBOS_IMAGE           Full image ref (overrides the argument if set after parse)
  JOBOS_GHCR_IMAGE      Image name without tag (default: ghcr.io/unownone/jobos)
  HUB_PUBLIC_HOST       Hostname, IP, or IP:port for invite URLs
  HUB_PUBLIC_URL        Full origin (wins over HUB_PUBLIC_HOST)
  JOBOS_HEALTH_URL      Health probe (default: http://127.0.0.1:8787/health)
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ -f "${HOME}/.jobos/deploy.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "${HOME}/.jobos/deploy.env"
  set +a
fi

REF="${1:-${JOBOS_IMAGE:-}}"
if [[ -z "$REF" ]]; then
  echo "hub_apply_image: pass a release tag or image ref" >&2
  usage >&2
  exit 1
fi

if [[ "$REF" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "hub_apply_image: raw git SHAs are not image tags. Use the GitHub Release tag (vYYYY.MM.DD-<sha7>)." >&2
  exit 1
fi

DEFAULT_IMAGE_NAME="${JOBOS_GHCR_IMAGE:-ghcr.io/unownone/jobos}"
if [[ "$REF" == *":"* || "$REF" == *"/"* ]]; then
  IMAGE="$REF"
else
  IMAGE="${DEFAULT_IMAGE_NAME}:${REF}"
fi
TAG="${IMAGE##*:}"
export JOBOS_IMAGE="$IMAGE"

DEPLOY_DIR="${JOBOS_DEPLOY_DIR:-${HOME}/jobos}"
COMPOSE_FILE="${JOBOS_COMPOSE_FILE:-compose.yml}"
HEALTH_URL="${JOBOS_HEALTH_URL:-http://127.0.0.1:8787/health}"
STATE_DIR="${JOBOS_STATE_DIR:-${HOME}/.jobos}"
mkdir -p "$STATE_DIR"

if [[ ! -f "$DEPLOY_DIR/$COMPOSE_FILE" ]]; then
  echo "hub_apply_image: missing $DEPLOY_DIR/$COMPOSE_FILE" >&2
  exit 1
fi
if [[ ! -f "$DEPLOY_DIR/traefik/traefik.yml" || ! -f "$DEPLOY_DIR/traefik/dynamic.yml" ]]; then
  echo "hub_apply_image: missing traefik files under $DEPLOY_DIR/traefik" >&2
  exit 1
fi

cd "$DEPLOY_DIR"

echo "Job Hub image apply"
echo "  dir:    $DEPLOY_DIR"
echo "  image:  $JOBOS_IMAGE"
echo "  tag:    $TAG"
if [[ -n "${HUB_PUBLIC_URL:-}" ]]; then
  echo "  public: $HUB_PUBLIC_URL"
elif [[ -n "${HUB_PUBLIC_HOST:-}" ]]; then
  echo "  public host: $HUB_PUBLIC_HOST"
fi

docker_cmd() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
    return
  fi
  sudo -n docker "$@"
}

docker_cmd compose -f "$COMPOSE_FILE" pull hub
docker_cmd compose -f "$COMPOSE_FILE" up -d --remove-orphans

ok=0
for _ in $(seq 1 36); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 5
done
if [[ "$ok" != "1" ]]; then
  echo "hub_apply_image: health check failed at $HEALTH_URL" >&2
  docker_cmd compose -f "$COMPOSE_FILE" ps >&2 || true
  docker_cmd compose -f "$COMPOSE_FILE" logs --tail 80 hub >&2 || true
  exit 1
fi

printf '%s\n' "$TAG" > "$STATE_DIR/deployed.tag"
printf '%s\n' "$JOBOS_IMAGE" > "$STATE_DIR/deployed.image"
curl -sS "$HEALTH_URL"
echo
echo "deployed $TAG"
