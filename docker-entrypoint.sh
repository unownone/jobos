#!/usr/bin/env bash
# Wait for PostgreSQL, then start Hub. Hub is stateless — no /data volume.
set -euo pipefail

export BOARD_DB="${BOARD_DB:-/tmp/board.db}"
export HUB_PACKS_DIR="${HUB_PACKS_DIR:-/tmp/jobos-packs}"
export HUB_REPO_ROOT="${HUB_REPO_ROOT:-/app}"
export JOBOS_NONINTERACTIVE=1
export PATH="/usr/local/bin:${PATH}"

# Railway / Render inject PORT. Bind Hub there so healthchecks hit the process.
if [[ -n "${PORT:-}" ]]; then
  export BOARD_PORT="$PORT"
fi

mkdir -p "${HUB_PACKS_DIR}"

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

# The Go API retries Postgres itself. An empty DATABASE_URL keeps the memory store.
exec bash /app/board/start.sh
