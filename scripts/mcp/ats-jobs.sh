#!/usr/bin/env bash
# Pin: PyPI ats-jobs-mcp 1.0.0 — directory.json ships in the wheel, not this git repo
set -euo pipefail
exec uvx --from "ats-jobs-mcp==1.0.0" ats-jobs-mcp "$@"
