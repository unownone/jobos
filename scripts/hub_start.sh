#!/usr/bin/env bash
# Interactive Hub start. Asks for the public host on a TTY, then runs hub_deploy.sh.
# Docker / noninteractive callers should run scripts/hub_deploy.sh directly.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
HUB_DIR="${JOBHUB_DIR:-$REPO/.hub}"
export PATH="$HOME/.local/bin:$PATH"

jobos_normalize_url() {
  local raw="${1:-}"
  raw="${raw#"${raw%%[![:space:]]*}"}"
  raw="${raw%"${raw##*[![:space:]]}"}"
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

jobos_default_host() {
  if [[ -n "${HUB_PUBLIC_HOST:-}" ]]; then
    echo "$HUB_PUBLIC_HOST"
    return 0
  fi
  if [[ -n "${HUB_PUBLIC_URL:-}" ]]; then
    local stripped="${HUB_PUBLIC_URL#http://}"
    stripped="${stripped#https://}"
    echo "${stripped%/}"
    return 0
  fi
  hostname -I 2>/dev/null | awk '{print $1}'
}

# Prefer .hub secrets. Legacy board/.env is migrated by hub_deploy.sh on first run.
if [[ -f "$HUB_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$HUB_DIR/.env"
  set +a
elif [[ -f "$REPO/board/.env" ]]; then
  # Source for HUB_PUBLIC_* prompts only; tokens migrate in hub_deploy.sh.
  set -a
  # shellcheck disable=SC1091
  source "$REPO/board/.env"
  set +a
fi

if [[ "${JOBOS_NONINTERACTIVE:-}" != "1" && "${HUB_DEPLOY_DRY_RUN:-}" != "1" && -t 0 ]]; then
  if [[ -z "${HUB_PUBLIC_URL:-}" && -z "${HUB_PUBLIC_HOST:-}" ]]; then
    echo "Job Hub setup"
    echo "  Invites and signup links use this public host."
    echo "  Examples: hunt.example.com  |  12.234.244.34  |  12.234.244.34:343"
    default_host="$(jobos_default_host)"
    read -r -p "Public host [${default_host}]: " entered
    entered="${entered:-$default_host}"
    export HUB_PUBLIC_HOST="$entered"
    export HUB_PUBLIC_URL="$(jobos_normalize_url "$entered")"
    echo "  Public origin: ${HUB_PUBLIC_URL}"
  fi
fi

if [[ -z "${HUB_PUBLIC_URL:-}" && -n "${HUB_PUBLIC_HOST:-}" ]]; then
  export HUB_PUBLIC_URL="$(jobos_normalize_url "$HUB_PUBLIC_HOST")"
fi

upsert_env() {
  local file="$1" key="$2" value="$3" line found=0 tmp
  [[ -n "$value" ]] || return 0
  tmp="$(mktemp)"
  if [[ -f "$file" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      if [[ "$line" == "$key="* ]]; then
        printf '%s=%s\n' "$key" "$value"
        found=1
      else
        printf '%s\n' "$line"
      fi
    done < "$file" > "$tmp"
  fi
  if [[ "$found" == 0 ]]; then
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
  fi
  mv "$tmp" "$file"
}

if [[ -n "${HUB_PUBLIC_URL:-}" || -n "${HUB_PUBLIC_HOST:-}" ]]; then
  mkdir -p "$HUB_DIR"
  touch "$HUB_DIR/.env"
  upsert_env "$HUB_DIR/.env" HUB_PUBLIC_HOST "${HUB_PUBLIC_HOST:-}"
  upsert_env "$HUB_DIR/.env" HUB_PUBLIC_URL "${HUB_PUBLIC_URL:-}"
fi

export BOARD_HOST="${BOARD_HOST:-0.0.0.0}"
if [[ -n "${PORT:-}" ]]; then
  export BOARD_PORT="$PORT"
else
  export BOARD_PORT="${BOARD_PORT:-8787}"
fi
export HUB_ADDR="${HUB_ADDR:-${BOARD_HOST}:${BOARD_PORT}}"
export HUB_REPO_ROOT="${HUB_REPO_ROOT:-$REPO}"
export HUB_WEB_ROOT="${HUB_WEB_ROOT:-$REPO/web/dist}"
export JOBHUB_DIR="$HUB_DIR"

echo "Job Hub → http://${BOARD_HOST}:${BOARD_PORT}/  (Go API, SPA from web/dist)"
echo "Sibling agents: ${HUB_PUBLIC_URL:-http://127.0.0.1:${BOARD_PORT}}/api/jobs with Bearer keys (or X-Role + X-Token compat)"

exec bash "$REPO/scripts/hub_deploy.sh"
