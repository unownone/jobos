#!/usr/bin/env bash
# Apply Hub Postgres schema. Migrations are manual — the API does not migrate on boot.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "hub_migrate: set DATABASE_URL" >&2
  exit 1
fi

if command -v docker >/dev/null 2>&1 && [[ "${HUB_MIGRATE_DOCKER:-}" == "1" ]]; then
  exec docker compose run --rm --no-deps migrate
fi

cd server
exec go run ./cmd/hub migrate
