#!/usr/bin/env bash
# Capture README screenshots of the live admin UI into board/docs/.
# Requires a running board (bash board/start.sh) and gitignored admin token.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
DOCS="$ROOT/docs"
mkdir -p "$DOCS"

if [[ ! -f "$ROOT/.env" ]]; then
  echo "board/.env missing. Generate tokens first: uv run scripts/board_gen_tokens.py --print" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

BOARD_URL="${BOARD_URL:-http://127.0.0.1:${BOARD_PORT:-8787}}"
if ! curl -sf "$BOARD_URL/health" >/dev/null; then
  echo "Board not reachable at $BOARD_URL. Start it with bash board/start.sh" >&2
  exit 1
fi

stamp="$(date +%s)"

create_job() {
  local id="$1" company="$2" title="$3" status="$4" loc="${5:-}"
  curl -sf "$BOARD_URL/api/jobs" \
    -H "X-Role: discovery" -H "X-Token: $BOARD_TOKEN_DISCOVERY" \
    -H "Content-Type: application/json" \
    -d "{\"id\":\"$id\",\"company\":\"$company\",\"title\":\"$title\",\"apply_url\":\"https://example.invalid/$id\",\"sources\":[\"screenshot\"],\"status\":\"$status\",\"score\":4,\"location\":\"$loc\"}" \
    >/dev/null || true
}

patch_job() {
  local role="$1" token="$2" id="$3" body="$4"
  curl -sf -X PATCH "$BOARD_URL/api/jobs/$id" \
    -H "X-Role: $role" -H "X-Token: $token" \
    -H "Content-Type: application/json" \
    -d "$body" >/dev/null || true
}

# Synthetic rows only — never invent a real hunt. Varied chips for the walkthrough.
create_job "shot__blocked-${stamp}" "DemoCo" "Backend Engineer Distributed Systems" "apply_ready" "Remote"
create_job "shot__wait-${stamp}" "ExampleInfra" "Member of Technical Staff" "apply_ready" "Remote"
create_job "shot__skip-${stamp}" "Northwind" "Senior Backend Engineer" "skipped" "Remote"
create_job "shot__out-${stamp}" "AtlasLab" "Senior Software Engineer" "apply_ready" "Remote"
create_job "shot__ready-${stamp}" "HarborSys" "Backend Engineer (Go)" "apply_ready" "Remote"
create_job "shot__stop-${stamp}" "CedarWorks" "Platform Engineer" "apply_ready" "Remote"

patch_job apply "$BOARD_TOKEN_APPLY" "shot__blocked-${stamp}" '{"status":"apply_blocked","notes":"work-auth question"}'
patch_job apply "$BOARD_TOKEN_APPLY" "shot__wait-${stamp}" '{"status":"applied"}'
patch_job outreach "$BOARD_TOKEN_OUTREACH" "shot__wait-${stamp}" '{"status":"waiting"}'
patch_job apply "$BOARD_TOKEN_APPLY" "shot__out-${stamp}" '{"status":"applied"}'
patch_job outreach "$BOARD_TOKEN_OUTREACH" "shot__out-${stamp}" '{"status":"outreaching"}'

curl -sf -X POST "$BOARD_URL/api/jobs/shot__stop-${stamp}/stop" \
  -H "X-Role: admin" -H "X-Token: $BOARD_TOKEN_ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"reason":"duplicate of HarborSys row"}' >/dev/null || true

export BOARD_URL BOARD_TOKEN_ADMIN
export SHOT_DASH="$DOCS/01-dashboard.png"
export SHOT_FILTERS="$DOCS/02-filters.png"
export SHOT_DETAIL="$DOCS/03-detail.png"
export SHOT_DETAIL_ID="shot__blocked-${stamp}"

cd "$ROOT"
uv run --with playwright python "$ROOT/scripts/capture_readme_shots.py"
echo "wrote $SHOT_DASH $SHOT_FILTERS $SHOT_DETAIL"
