#!/usr/bin/env sh
# Probe the Hub listen address with the same precedence as config.listenAddr:
# HUB_ADDR, then PORT, then BOARD_PORT, then 8787.
set -eu

trim() {
  # shellcheck disable=SC2086
  set -- $1
  printf '%s' "$*"
}

addr="$(trim "${HUB_ADDR:-}")"
if [ -n "$addr" ]; then
  case "$addr" in
    *:*) ;;
    *) addr=":${addr}" ;;
  esac
  case "$addr" in
    :*) hostport="127.0.0.1${addr}" ;;
    *) hostport="$addr" ;;
  esac
else
  port="$(trim "${PORT:-}")"
  if [ -z "$port" ]; then
    port="$(trim "${BOARD_PORT:-8787}")"
  fi
  hostport="127.0.0.1:${port}"
fi

exec curl -fsS "http://${hostport}/health" >/dev/null
