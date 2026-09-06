#!/usr/bin/env bash
# Pin: PyPI workatastartup-mcp 0.1.2 (see vendor/mcp/PINNED.txt)
set -euo pipefail
exec uvx --from "workatastartup-mcp==0.1.2" workatastartup-mcp "$@"
