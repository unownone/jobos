#!/usr/bin/env bash
set -euo pipefail
ROOT="$("$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_repo_root.sh")"
exec uv run --directory "$ROOT/vendor/mcp/workatastartup-mcp" workatastartup-mcp "$@"
