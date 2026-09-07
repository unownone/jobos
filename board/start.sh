#!/usr/bin/env bash
# Start Job Hub (hunt board) on 0.0.0.0 so sibling agents on this host can reach it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.local/bin:$PATH"

if [[ ! -f "$ROOT/.env" && ! -f "$ROOT/tokens.local.json" ]]; then
  echo "No role tokens yet. Generating gitignored board/.env ..."
  uv run "$REPO/scripts/board_gen_tokens.py" --dir "$ROOT" --print
else
  uv run "$REPO/scripts/board_gen_tokens.py" --dir "$ROOT"
fi

uv run "$REPO/scripts/hub_ensure_bootstrap.py" --dir "$ROOT"
uv run "$REPO/scripts/hub_build_pack.py" --dir "$ROOT" --repo "$REPO"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

HOST="${BOARD_HOST:-0.0.0.0}"
PORT="${BOARD_PORT:-8787}"

echo "Job Hub → http://${HOST}:${PORT}/  (Board UI)"
echo "Gitignored secrets: ${ROOT}/.env ${ROOT}/tokens.local.json"
if [[ -n "${HUB_BOOTSTRAP_TOKEN:-}" && "${HUB_BOOTSTRAP_USED:-}" != "1" ]]; then
  PUBLIC="${HUB_PUBLIC_URL:-http://127.0.0.1:${PORT}}"
  PUBLIC="${PUBLIC%/}"
  echo "Admin signup: ${PUBLIC}/admin/signup#bootstrap=${HUB_BOOTSTRAP_TOKEN}"
fi
echo "Sibling agents: http://<this-host>:${PORT}/api/jobs with X-Role + X-Token (compat)"
echo "Maintainer owns this process. Do not commit .env or data/*.db"

exec uv run uvicorn app.main:create_app --factory --host "$HOST" --port "$PORT"
