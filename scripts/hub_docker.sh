#!/usr/bin/env bash
# One-shot Docker + Traefik install for Job Hub.
# Prompts for the public host (hostname, IP, or IP:port) unless HUB_PUBLIC_HOST is set.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
export PATH="$HOME/.local/bin:$PATH"

jobos_normalize_url() {
  local raw="${1:-}"
  raw="${raw%/}"
  if [[ -z "$raw" ]]; then
    echo ""
    return 0
  fi
  if [[ "$raw" == *"://"* ]]; then
    echo "$raw"
    return 0
  fi
  local port="${raw##*:}"
  if [[ "$raw" == *:* && "$port" == "443" ]]; then
    echo "https://${raw}"
    return 0
  fi
  echo "http://${raw}"
}

if ! command -v docker >/dev/null 2>&1; then
  echo "hub_docker: docker is required on PATH" >&2
  exit 1
fi

default_host="${HUB_PUBLIC_HOST:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
if [[ -z "${HUB_PUBLIC_HOST:-}" && -t 0 ]]; then
  echo "Job Hub Docker + Traefik (ports 80 and 443, board at /)"
  echo "  Examples: hunt.example.com  |  12.234.244.34  |  12.234.244.34:343"
  read -r -p "Public host [${default_host}]: " entered
  HUB_PUBLIC_HOST="${entered:-$default_host}"
fi
HUB_PUBLIC_HOST="${HUB_PUBLIC_HOST:-$default_host}"
if [[ -z "${HUB_PUBLIC_URL:-}" ]]; then
  HUB_PUBLIC_URL="$(jobos_normalize_url "$HUB_PUBLIC_HOST")"
fi
export HUB_PUBLIC_HOST HUB_PUBLIC_URL

echo "Public origin: ${HUB_PUBLIC_URL}"
echo "Traefik: :80 and :443 → Hub /"
exec docker compose -f "$REPO/docker-compose.yml" up -d --build "$@"
