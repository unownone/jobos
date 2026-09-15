#!/usr/bin/env bash
# Print the GitHub Release / GHCR tag for a commit.
# Format: vYYYY.MM.DD-<sha7>  (UTC date of the run, first 7 chars of the SHA)
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: jobos_release_tag.sh [sha] [YYYY.MM.DD]

  sha         40-char or short git SHA (default: GITHUB_SHA or git HEAD)
  YYYY.MM.DD  UTC date (default: today)

Prints one tag, e.g. v2026.09.15-a1b2c3d
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

sha="${1:-${GITHUB_SHA:-}}"
if [[ -z "$sha" ]]; then
  sha="$(git rev-parse HEAD)"
fi
sha="${sha#sha-}"
if [[ ! "$sha" =~ ^[0-9a-fA-F]{7,40}$ ]]; then
  echo "jobos_release_tag: not a git SHA: $sha" >&2
  exit 1
fi
short="$(printf '%s' "$sha" | cut -c1-7 | tr 'A-F' 'a-f')"

day="${2:-}"
if [[ -z "$day" ]]; then
  day="$(date -u +%Y.%m.%d)"
fi
if [[ ! "$day" =~ ^[0-9]{4}\.[0-9]{2}\.[0-9]{2}$ ]]; then
  echo "jobos_release_tag: date must be YYYY.MM.DD: $day" >&2
  exit 1
fi

printf 'v%s-%s\n' "$day" "$short"
