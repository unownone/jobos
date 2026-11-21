#!/usr/bin/env bash
# Bring up the Go API + SPA stack used for browser checks.
# Playwright Python suites were removed with the Python Hub. Use this compose
# stack for manual browser passes against http://127.0.0.1:18787.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f docker-compose.e2e.yml -p jobos-e2e)
"${COMPOSE[@]}" up -d --build

ok=0
for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:18787/health >/dev/null 2>&1 || curl -fsS http://127.0.0.1:18787/ >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 2
done
if [[ "$ok" -ne 1 ]]; then
  "${COMPOSE[@]}" logs
  exit 1
fi

echo "Hub e2e stack is up at http://127.0.0.1:18787"
echo "Tear down with: docker compose -f docker-compose.e2e.yml -p jobos-e2e down -v"
