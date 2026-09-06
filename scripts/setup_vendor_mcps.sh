#!/usr/bin/env bash
# Install local MCP runtime deps. --refresh re-clones pinned upstreams.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$ROOT/vendor/mcp"
REFRESH=0
if [[ "${1:-}" == "--refresh" ]]; then
  REFRESH=1
fi

clone_one() {
  local name="$1" sha="$2" url="$3"
  local dest="$VENDOR/$name"
  local tmp
  tmp="$(mktemp -d)"
  git clone --depth 1 "$url" "$tmp"
  git -C "$tmp" fetch --depth 1 origin "$sha"
  git -C "$tmp" checkout --detach "$sha"
  rm -rf "$dest"
  mkdir -p "$dest"
  cp -a "$tmp/." "$dest/"
  rm -rf "$dest/.git" "$tmp"
}

if [[ "$REFRESH" -eq 1 ]]; then
  while read -r name sha url; do
    [[ -z "${name:-}" || "$name" == \#* ]] && continue
    echo "refresh $name @ $sha"
    clone_one "$name" "$sha" "$url"
  done < <(awk 'NF==3 {print}' "$VENDOR/PINNED.txt")
fi

if [[ -f "$VENDOR/job-scout-mcp/package.json" ]]; then
  npm --prefix "$VENDOR/job-scout-mcp" ci --no-audit --no-fund
  npm --prefix "$VENDOR/job-scout-mcp" run build
fi

echo "setup_vendor_mcps: python MCPs start via uv run on first use"
echo "setup_vendor_mcps: job-scout node_modules ready"
