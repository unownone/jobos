#!/usr/bin/env bash
# Idempotent clone + npm install of dzhng/deep-research for cloud agents.
# Does not start the API (needs FIRECRAWL_KEY + OPENAI_KEY / FIREWORKS_KEY).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${JOBOS_DEEP_RESEARCH_DIR:-$ROOT/agent-tools/open-deep-research}"
REPO_URL="${JOBOS_DEEP_RESEARCH_REPO:-https://github.com/dzhng/deep-research.git}"

mkdir -p "$(dirname "$DEST")"

if [[ -d "$DEST/.git" ]]; then
  git -C "$DEST" fetch --depth 1 origin
  git -C "$DEST" reset --hard FETCH_HEAD
else
  rm -rf "$DEST"
  git clone --depth 1 "$REPO_URL" "$DEST"
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "setup_deep_research: npm is required (Node 22.x). Skip install." >&2
  exit 0
fi

# tsx lives in upstream devDependencies and is required for `npm run api`.
npm --prefix "$DEST" ci --no-audit --no-fund \
  || npm --prefix "$DEST" install --no-audit --no-fund

echo "setup_deep_research: ready at $DEST"
echo "setup_deep_research: run the cloned tool with npm --prefix \"$DEST\" run api"
