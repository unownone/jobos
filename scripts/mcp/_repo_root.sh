#!/usr/bin/env bash
# Resolve Job Apply OS repo root from a script under scripts/mcp/.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "$(cd "$HERE/../.." && pwd)"
