#!/usr/bin/env bash
# Wait for PostgreSQL, then start Hub. Hub is stateless — no /data volume.
set -euo pipefail

export BOARD_DB="${BOARD_DB:-/tmp/board.db}"
export HUB_PACKS_DIR="${HUB_PACKS_DIR:-/tmp/jobos-packs}"
export HUB_REPO_ROOT="${HUB_REPO_ROOT:-/app}"
export JOBOS_NONINTERACTIVE=1
export PATH="/usr/local/bin:/app/board/.venv/bin:${PATH}"

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

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "docker-entrypoint: DATABASE_URL is required (PostgreSQL). Hub does not use a data volume." >&2
  exit 1
fi

python - <<'PY'
import os
import sys
import time

import psycopg

url = os.environ["DATABASE_URL"]
last = ""
for _ in range(60):
    try:
        with psycopg.connect(url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        sys.exit(0)
    except Exception as exc:
        last = str(exc)
        time.sleep(1)
print(f"docker-entrypoint: postgres not ready: {last}", file=sys.stderr)
sys.exit(1)
PY

exec bash /app/board/start.sh
