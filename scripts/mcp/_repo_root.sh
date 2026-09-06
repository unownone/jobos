#!/usr/bin/env bash
# Resolve Job Apply OS repo root from a script under scripts/ or scripts/mcp/.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -d "$HERE/../vendor/mcp" ]]; then
  echo "$(cd "$HERE/.." && pwd)"
elif [[ -d "$HERE/../../vendor/mcp" ]]; then
  echo "$(cd "$HERE/../.." && pwd)"
else
  git -C "$HERE" rev-parse --show-toplevel
fi
