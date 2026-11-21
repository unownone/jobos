#!/usr/bin/env sh
# Probe the Hub listen port. Railway/Render set PORT; Coolify compose uses BOARD_PORT.
set -eu
port="${PORT:-${BOARD_PORT:-8787}}"
exec curl -fsS "http://127.0.0.1:${port}/health" >/dev/null
