#!/usr/bin/env bash
# Start the hunt board on 0.0.0.0 so sibling agents on this host can reach it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
cd "$ROOT"

if [[ ! -f "$ROOT/.env" && ! -f "$ROOT/tokens.local.json" ]]; then
  echo "No role tokens yet. Generating gitignored board/.env ..."
  uv run "$REPO/scripts/board_gen_tokens.py" --dir "$ROOT" --print
fi

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

HOST="${BOARD_HOST:-0.0.0.0}"
PORT="${BOARD_PORT:-8787}"

echo "Get That Job hunt board → http://${HOST}:${PORT}/  (admin UI)"
echo "Sibling agents: http://<this-host>:${PORT}/api/jobs with X-Role + X-Token"
echo "Maintainer owns this process. Do not commit .env or data/*.db"

exec uv run uvicorn app.main:create_app --factory --host "$HOST" --port "$PORT"
