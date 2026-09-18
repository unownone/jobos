#!/usr/bin/env bash
# Deploy Job Hub (the board FastAPI process). No second service.
# Cursor Cloud: binds 0.0.0.0:8787; Docker is optional and not required.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BOARD="${JOBHUB_BOARD_DIR:-$REPO/board}"
export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  if [[ -f "$REPO/scripts/setup_uv.sh" ]]; then
    bash "$REPO/scripts/setup_uv.sh"
  fi
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "hub_deploy: uv is required on PATH (see scripts/setup_uv.sh)" >&2
  exit 1
fi

export BOARD_HOST="${BOARD_HOST:-0.0.0.0}"
export BOARD_PORT="${BOARD_PORT:-8787}"

echo "Job Hub deploy"
echo "  bind: ${BOARD_HOST}:${BOARD_PORT}"
echo "  gitignored secrets: ${BOARD}/.env ${BOARD}/tokens.local.json"
echo "  postgres: ${DATABASE_URL:-set DATABASE_URL}"
if [[ -n "${HUB_PUBLIC_URL:-}" ]]; then
  echo "  public url: ${HUB_PUBLIC_URL}"
fi

uv run --project "$BOARD" --frozen --no-dev python "$REPO/scripts/board_gen_tokens.py" --dir "$BOARD"
uv run --project "$BOARD" --frozen --no-dev python "$REPO/scripts/hub_ensure_bootstrap.py" --dir "$BOARD"
uv run --project "$BOARD" --frozen --no-dev python "$REPO/scripts/hub_build_pack.py" --dir "$BOARD" --repo "$REPO"

if [[ "${HUB_DEPLOY_DRY_RUN:-}" == "1" ]]; then
  echo "HUB_DEPLOY_DRY_RUN=1 — not starting gunicorn"
  exit 0
fi

exec bash "$BOARD/start.sh"
