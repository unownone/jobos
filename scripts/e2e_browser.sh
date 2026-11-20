#!/usr/bin/env bash
# Browser e2e: Compose Hub when Docker exists, else the local Go API and SPA.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="$ROOT/docker-compose.e2e.yml"
COMPOSE_PROJECT="jobos-e2e"
COMPOSE_URL="http://127.0.0.1:18787"
STARTED_COMPOSE=0

have_docker() {
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
}

wait_health() {
  local url="$1"
  local i
  for i in $(seq 1 90); do
    if curl -fsS "$url/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "Hub at $url never became healthy" >&2
  return 1
}

cleanup() {
  if [[ "$STARTED_COMPOSE" == "1" && "${E2E_KEEP:-}" != "1" ]]; then
    docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" down -v >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ -n "${E2E_HUB_URL:-}" ]]; then
  wait_health "${E2E_HUB_URL}"
elif [[ "${E2E_BACKEND:-}" != "local" ]] && have_docker; then
  docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" up -d --build
  STARTED_COMPOSE=1
  export E2E_HUB_URL="$COMPOSE_URL"
  export E2E_BACKEND="${E2E_BACKEND:-external}"
  wait_health "$E2E_HUB_URL"
else
  export E2E_BACKEND=local
fi

if [[ -x /usr/local/bin/google-chrome || -x /usr/bin/google-chrome ]]; then
  export E2E_BROWSER_CHANNEL="${E2E_BROWSER_CHANNEL:-chrome}"
fi

cd "$ROOT/board"
uv sync --group dev

cd "$ROOT/e2e"
uv sync
if [[ -z "${E2E_BROWSER_CHANNEL:-}" ]]; then
  uv run playwright install chromium
fi

uv run pytest -c pytest.ini --strict-markers --tb=short "$@"
