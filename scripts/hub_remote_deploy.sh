#!/usr/bin/env bash
# From a GitHub-hosted runner: SSH to the Job Hub host, copy compose+traefik
# (not the git tree), pull the GHCR tag, and apply it.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: hub_remote_deploy.sh <tag-or-image>

Env:
  JOBOS_HOST              Hostname or IP of the Hub VM (required unless dry-run)
  JOBOS_HOST_USER         SSH user (default: opc)
  JOBOS_HOST_SSH_PORT     SSH port (default: 22)
  JOBOS_HOST_SSH_KEY      Path to private key (or contents via JOBOS_HOST_SSH_KEY_DATA)
  JOBOS_HOST_KNOWN_HOSTS  known_hosts blob (or path). If empty, ssh-keyscan is used.
  JOBOS_DEPLOY_DIR        Remote compose dir (default: /home/opc/jobos)
  JOBOS_IMAGE             Full image ref (optional; derived from tag)
  JOBOS_GHCR_IMAGE        Image name without tag (default: ghcr.io/unownone/jobos)
  GHCR_USERNAME           Registry user (default: github.repository_owner / unownone)
  GHCR_TOKEN              Token with read:packages (required unless dry-run)
  JOBOS_DEPLOY_DRY_RUN    If 1, print the plan and do not SSH
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REF="${1:-}"
if [[ -z "$REF" ]]; then
  echo "hub_remote_deploy: pass a release tag or image ref" >&2
  usage >&2
  exit 1
fi

DEFAULT_IMAGE_NAME="${JOBOS_GHCR_IMAGE:-ghcr.io/unownone/jobos}"
if [[ "$REF" == *":"* || "$REF" == *"/"* ]]; then
  IMAGE="$REF"
else
  IMAGE="${DEFAULT_IMAGE_NAME}:${REF}"
fi
TAG="${IMAGE##*:}"
HOST="${JOBOS_HOST:-}"
USER_NAME="${JOBOS_HOST_USER:-opc}"
PORT="${JOBOS_HOST_SSH_PORT:-22}"
DEPLOY_DIR="${JOBOS_DEPLOY_DIR:-/home/${USER_NAME}/jobos}"
GHCR_USER="${GHCR_USERNAME:-unownone}"
DRY="${JOBOS_DEPLOY_DRY_RUN:-0}"

need() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "hub_remote_deploy: missing $path" >&2
    exit 1
  fi
}
need "$ROOT/deploy/compose.yml"
need "$ROOT/traefik/traefik.yml"
need "$ROOT/traefik/dynamic.yml"
need "$ROOT/scripts/hub_apply_image.sh"

echo "Job Hub remote deploy"
echo "  image:  $IMAGE"
echo "  tag:    $TAG"
echo "  host:   ${USER_NAME}@${HOST:-<unset>}:${PORT}"
echo "  dir:    $DEPLOY_DIR"

if [[ "$DRY" == "1" ]]; then
  echo "dry-run: would scp compose.yml + traefik/ + hub_apply_image.sh"
  echo "dry-run: would docker login ghcr.io as ${GHCR_USER}"
  echo "dry-run: would JOBOS_IMAGE=$IMAGE bash hub_apply_image.sh $TAG"
  exit 0
fi

if [[ -z "$HOST" ]]; then
  echo "hub_remote_deploy: JOBOS_HOST is not set." >&2
  echo "Add repository variable JOBOS_HOST (or secret) — the OCI box hostname/IP." >&2
  exit 1
fi
if [[ -z "${GHCR_TOKEN:-}" ]]; then
  echo "hub_remote_deploy: GHCR_TOKEN is not set (needs packages:read to pull a private image)." >&2
  exit 1
fi

tmp="$(mktemp -d)"
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT
chmod 700 "$tmp"

key="$tmp/id"
if [[ -n "${JOBOS_HOST_SSH_KEY:-}" && -f "${JOBOS_HOST_SSH_KEY}" ]]; then
  cp "${JOBOS_HOST_SSH_KEY}" "$key"
elif [[ -n "${JOBOS_HOST_SSH_KEY_DATA:-}" ]]; then
  printf '%s\n' "${JOBOS_HOST_SSH_KEY_DATA}" | tr -d '\r' > "$key"
elif [[ -n "${JOBOS_HOST_SSH_KEY:-}" ]]; then
  printf '%s\n' "${JOBOS_HOST_SSH_KEY}" | tr -d '\r' > "$key"
else
  echo "hub_remote_deploy: set JOBOS_HOST_SSH_KEY to a private key that can SSH as ${USER_NAME}@${HOST}." >&2
  echo "Repository secret JOBOS_HOST_SSH_KEY (preferred) or JOBOS_DEPLOY_KEY (fallback)." >&2
  exit 1
fi
chmod 600 "$key"
if ! ssh-keygen -y -f "$key" >/dev/null 2>&1; then
  echo "hub_remote_deploy: JOBOS_HOST_SSH_KEY is not a usable OpenSSH private key" >&2
  exit 1
fi

known="$tmp/known_hosts"
if [[ -n "${JOBOS_HOST_KNOWN_HOSTS:-}" && -f "${JOBOS_HOST_KNOWN_HOSTS}" ]]; then
  cp "${JOBOS_HOST_KNOWN_HOSTS}" "$known"
elif [[ -n "${JOBOS_HOST_KNOWN_HOSTS:-}" ]]; then
  printf '%s\n' "${JOBOS_HOST_KNOWN_HOSTS}" | tr -d '\r' > "$known"
else
  echo "JOBOS_HOST_KNOWN_HOSTS unset; ssh-keyscan ${HOST} (TOFU). Pin the host key as a secret when you can."
  ssh-keyscan -p "$PORT" -H "$HOST" > "$known" 2>/dev/null || ssh-keyscan -p "$PORT" "$HOST" > "$known"
fi
if [[ ! -s "$known" ]]; then
  echo "hub_remote_deploy: empty known_hosts for $HOST" >&2
  exit 1
fi
chmod 644 "$known"

ssh_base=(
  ssh
  -i "$key"
  -p "$PORT"
  -o IdentitiesOnly=yes
  -o IdentityAgent=none
  -o PreferredAuthentications=publickey
  -o BatchMode=yes
  -o StrictHostKeyChecking=yes
  -o UserKnownHostsFile="$known"
  -o GlobalKnownHostsFile=/dev/null
  -o ConnectTimeout=20
)

bundle="$tmp/bundle"
mkdir -p "$bundle/traefik"
cp "$ROOT/deploy/compose.yml" "$bundle/compose.yml"
cp "$ROOT/traefik/traefik.yml" "$ROOT/traefik/dynamic.yml" "$bundle/traefik/"
cp "$ROOT/scripts/hub_apply_image.sh" "$bundle/hub_apply_image.sh"
chmod 0755 "$bundle/hub_apply_image.sh"

echo "copying compose + traefik (not the git tree) → ${USER_NAME}@${HOST}:${DEPLOY_DIR}"
tar -C "$bundle" -czf - . | "${ssh_base[@]}" "${USER_NAME}@${HOST}" \
  "mkdir -p $(printf '%q' "$DEPLOY_DIR") && tar -C $(printf '%q' "$DEPLOY_DIR") -xzf -"

echo "applying $IMAGE"
# Token is the first stdin line (not written to the remote disk, not in ssh argv).
# The rest of stdin is the apply script.
(
  printf '%s\n' "$GHCR_TOKEN"
  cat <<REMOTE
set -euo pipefail
export JOBOS_DEPLOY_DIR=$(printf '%q' "$DEPLOY_DIR")
export JOBOS_IMAGE=$(printf '%q' "$IMAGE")
export JOBOS_GHCR_IMAGE=$(printf '%q' "$DEFAULT_IMAGE_NAME")
ghcr_user=$(printf '%q' "$GHCR_USER")
tag=$(printf '%q' "$TAG")
docker_cmd() {
  if docker info >/dev/null 2>&1; then
    docker "\$@"
    return
  fi
  sudo -n docker "\$@"
}
printf '%s\\n' "\$GHCR_TOKEN" | docker_cmd login ghcr.io -u "\$ghcr_user" --password-stdin
unset GHCR_TOKEN
bash "\$JOBOS_DEPLOY_DIR/hub_apply_image.sh" "\$tag"
docker_cmd logout ghcr.io >/dev/null 2>&1 || true
REMOTE
) | "${ssh_base[@]}" "${USER_NAME}@${HOST}" 'IFS= read -r GHCR_TOKEN; export GHCR_TOKEN; bash -s'
