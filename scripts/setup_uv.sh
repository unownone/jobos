#!/usr/bin/env bash
# Idempotent install of uv, the runner the ledger/skill scripts and README use
# (`uv run scripts/rebuild_index.py`). Cloud-agent friendly: installs from PyPI,
# which is on the environment egress allowlist (astral.sh is not).
set -euo pipefail

if command -v uv >/dev/null 2>&1; then
  echo "setup_uv: uv already present ($(uv --version))"
  exit 0
fi

# --user drops uv into ~/.local/bin, which login shells already put on PATH.
# --break-system-packages is needed on Debian's externally-managed Python.
python3 -m pip install --user --break-system-packages 'uv>=0.4' \
  || python3 -m pip install --user 'uv>=0.4'

export PATH="$HOME/.local/bin:$PATH"
if command -v uv >/dev/null 2>&1; then
  echo "setup_uv: installed $(uv --version)"
else
  echo "setup_uv: uv not on PATH after install; add \$HOME/.local/bin to PATH" >&2
  exit 1
fi
