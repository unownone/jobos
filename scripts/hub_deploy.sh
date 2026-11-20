#!/usr/bin/env bash
# Deploy Job Hub as the Go API. It serves the built React SPA when web/dist exists.
# Default listen address is 0.0.0.0:8787. Docker is optional and not required.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# Python project + venv always live in repo board/. JOBHUB_BOARD_DIR is the
# secrets/data dir (defaults to that same package) so tests can isolate .env.
BOARD_PKG="$REPO/board"
BOARD="${JOBHUB_BOARD_DIR:-$BOARD_PKG}"
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
export HUB_ADDR="${HUB_ADDR:-${BOARD_HOST}:${BOARD_PORT}}"
export HUB_REPO_ROOT="${HUB_REPO_ROOT:-$REPO}"
export HUB_WEB_ROOT="${HUB_WEB_ROOT:-$REPO/web/dist}"
export HUB_PLUGINS="${HUB_PLUGINS:-off}"

echo "Job Hub deploy"
echo "  bind: ${HUB_ADDR}"
echo "  gitignored secrets: ${BOARD}/.env ${BOARD}/tokens.local.json"
echo "  postgres: ${DATABASE_URL:-set DATABASE_URL}"
if [[ -n "${HUB_PUBLIC_URL:-}" ]]; then
  echo "  public url: ${HUB_PUBLIC_URL}"
fi

if [[ ! -x "$BOARD_PKG/.venv/bin/python" ]]; then
  uv sync --project "$BOARD_PKG" --frozen --no-dev
fi
"$BOARD_PKG/.venv/bin/python" "$REPO/scripts/board_gen_tokens.py" --dir "$BOARD"
"$BOARD_PKG/.venv/bin/python" "$REPO/scripts/hub_ensure_bootstrap.py" --dir "$BOARD"
"$BOARD_PKG/.venv/bin/python" "$REPO/scripts/hub_build_pack.py" --dir "$BOARD" --repo "$REPO"

if [[ "${HUB_DEPLOY_DRY_RUN:-}" == "1" ]]; then
  echo "HUB_DEPLOY_DRY_RUN=1 — not starting the Go API"
  exit 0
fi

if [[ ! -f "${HUB_WEB_ROOT}/index.html" ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "hub_deploy: npm is required to build ${HUB_WEB_ROOT}" >&2
    exit 1
  fi
  npm install --prefix "$REPO/web"
  npm run build --prefix "$REPO/web"
fi
if ! command -v go >/dev/null 2>&1; then
  echo "hub_deploy: go is required to start the API" >&2
  exit 1
fi

cd "$REPO/server"
exec go run ./cmd/hub
