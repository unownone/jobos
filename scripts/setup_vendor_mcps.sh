#!/usr/bin/env bash
# Prefetch job-scout into gitignored agent-tools/. Python MCPs use uvx on first attach.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="${JOBOS_JOB_SCOUT_DIR:-$ROOT/agent-tools/job-scout-mcp}"
PINNED="${JOBOS_JOB_SCOUT_SHA:-b05841644a117b763a03ea0aef58705e5ec7c9e7}"
URL="${JOBOS_JOB_SCOUT_REPO:-https://github.com/pabnatanawan87/job-scout-mcp.git}"

if [[ ! -f "$DIR/dist/index.js" ]]; then
  mkdir -p "$(dirname "$DIR")"
  tmp="$(mktemp -d)"
  git clone --depth 1 "$URL" "$tmp"
  git -C "$tmp" fetch --depth 1 origin "$PINNED"
  git -C "$tmp" checkout --detach "$PINNED"
  rm -rf "$DIR"
  mkdir -p "$DIR"
  cp -a "$tmp/." "$DIR/"
  rm -rf "$DIR/.git" "$tmp"
  npm --prefix "$DIR" ci --no-audit --no-fund
  npm --prefix "$DIR" run build
fi

echo "setup_vendor_mcps: job-scout ready under agent-tools/ (gitignored)"
echo "setup_vendor_mcps: workatastartup-mcp==0.1.2 and ats-jobs-mcp==1.0.0 via uvx on first use"
