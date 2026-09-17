#!/usr/bin/env bash
# Persist Hub sqlite + secrets on /data. Resolve HUB_PUBLIC_HOST into HUB_PUBLIC_URL.
set -euo pipefail

mkdir -p /data/packs /data/profiles
if [[ ! -f /data/hub.env ]]; then
  : > /data/hub.env
fi
if [[ ! -s /data/tokens.local.json ]]; then
  printf '%s\n' '{}' > /data/tokens.local.json
fi
ln -sfn /data/hub.env /app/board/.env
ln -sfn /data/tokens.local.json /app/board/tokens.local.json

export BOARD_DB="${BOARD_DB:-/data/board.db}"
export HUB_PACKS_DIR="${HUB_PACKS_DIR:-/data/packs}"
export HUB_REPO_ROOT="${HUB_REPO_ROOT:-/app}"
export JOBOS_NONINTERACTIVE=1
export PATH="/usr/local/bin:/app/board/.venv/bin:${PATH}"

# Railway / Render inject PORT. Bind Hub there so healthchecks hit the process.
if [[ -n "${PORT:-}" ]]; then
  export BOARD_PORT="$PORT"
fi

if [[ -z "${HUB_PUBLIC_URL:-}" && -n "${HUB_PUBLIC_HOST:-}" ]]; then
  host="${HUB_PUBLIC_HOST%/}"
  if [[ "$host" == *"://"* ]]; then
    export HUB_PUBLIC_URL="$host"
  elif [[ "$host" == *:443 ]]; then
    export HUB_PUBLIC_URL="https://${host}"
  else
    export HUB_PUBLIC_URL="http://${host}"
  fi
fi

exec bash /app/board/start.sh
