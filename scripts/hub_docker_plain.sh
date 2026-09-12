#!/usr/bin/env bash
# Plain Docker Compose install (Hub on :8787, no Traefik).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

if ! command -v docker >/dev/null 2>&1; then
  echo "hub_docker_plain: docker is required on PATH" >&2
  exit 1
fi

default_host="${HUB_PUBLIC_HOST:-127.0.0.1:${HUB_PORT:-8787}}"
if [[ -z "${HUB_PUBLIC_HOST:-}" && -t 0 ]]; then
  echo "Job Hub Docker (plain, port ${HUB_PORT:-8787}, no Traefik)"
  read -r -p "Public host [${default_host}]: " entered
  HUB_PUBLIC_HOST="${entered:-$default_host}"
fi
HUB_PUBLIC_HOST="${HUB_PUBLIC_HOST:-$default_host}"
if [[ -z "${HUB_PUBLIC_URL:-}" ]]; then
  if [[ "$HUB_PUBLIC_HOST" == *"://"* ]]; then
    HUB_PUBLIC_URL="${HUB_PUBLIC_HOST%/}"
  else
    HUB_PUBLIC_URL="http://${HUB_PUBLIC_HOST}"
  fi
fi
export HUB_PUBLIC_HOST HUB_PUBLIC_URL

echo "Public origin: ${HUB_PUBLIC_URL}"
echo "First step after admin signup: ${HUB_PUBLIC_URL}/onboarding"
exec docker compose -f "$REPO/docker-compose.plain.yml" up -d --build "$@"
