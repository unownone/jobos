#!/usr/bin/env bash
set -euo pipefail
ROOT="$("$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_repo_root.sh")"
DIR="$ROOT/vendor/mcp/job-scout-mcp"
if [[ ! -f "$DIR/dist/index.js" ]]; then
  echo "job-scout: dist missing; run bash scripts/setup_vendor_mcps.sh" >&2
  exit 1
fi
if [[ ! -d "$DIR/node_modules" ]]; then
  npm --prefix "$DIR" ci --omit=dev --no-audit --no-fund
fi
exec node "$DIR/dist/index.js" "$@"
