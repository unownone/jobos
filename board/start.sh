#!/usr/bin/env bash
# Start Job Hub (hunt board). Interactive on a TTY; Docker sets JOBOS_NONINTERACTIVE=1.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.local/bin:$PATH"

jobos_normalize_url() {
  local raw="${1:-}"
  raw="${raw#"${raw%%[![:space:]]*}"}"
  raw="${raw%"${raw##*[![:space:]]}"}"
  raw="${raw%/}"
  if [[ -z "$raw" ]]; then
    echo ""
    return 0
  fi
  if [[ "$raw" == *"://"* ]]; then
    echo "$raw"
    return 0
  fi
  local port="${raw##*:}"
  if [[ "$raw" == *:* && "$port" == "443" ]]; then
    echo "https://${raw}"
    return 0
  fi
  echo "http://${raw}"
}

jobos_default_host() {
  if [[ -n "${HUB_PUBLIC_HOST:-}" ]]; then
    echo "$HUB_PUBLIC_HOST"
    return 0
  fi
  if [[ -n "${HUB_PUBLIC_URL:-}" ]]; then
    local stripped="${HUB_PUBLIC_URL#http://}"
    stripped="${stripped#https://}"
    echo "${stripped%/}"
    return 0
  fi
  hostname -I 2>/dev/null | awk '{print $1}'
}

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

if [[ "${JOBOS_NONINTERACTIVE:-}" != "1" && "${HUB_DEPLOY_DRY_RUN:-}" != "1" && -t 0 ]]; then
  if [[ -z "${HUB_PUBLIC_URL:-}" && -z "${HUB_PUBLIC_HOST:-}" ]]; then
    echo "Job Hub setup"
    echo "  Invites and signup links use this public host."
    echo "  Examples: hunt.example.com  |  12.234.244.34  |  12.234.244.34:343"
    default_host="$(jobos_default_host)"
    read -r -p "Public host [${default_host}]: " entered
    entered="${entered:-$default_host}"
    export HUB_PUBLIC_HOST="$entered"
    export HUB_PUBLIC_URL="$(jobos_normalize_url "$entered")"
    echo "  Public origin: ${HUB_PUBLIC_URL}"
  fi
fi

if [[ -z "${HUB_PUBLIC_URL:-}" && -n "${HUB_PUBLIC_HOST:-}" ]]; then
  export HUB_PUBLIC_URL="$(jobos_normalize_url "$HUB_PUBLIC_HOST")"
fi

if [[ -n "${HUB_PUBLIC_URL:-}" || -n "${HUB_PUBLIC_HOST:-}" ]]; then
  python3 - "$ROOT/.env" "${HUB_PUBLIC_HOST:-}" "${HUB_PUBLIC_URL:-}" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
host, url = sys.argv[2], sys.argv[3]
existing = {}
if path.is_file():
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        existing[k.strip()] = v.strip()
if host:
    existing["HUB_PUBLIC_HOST"] = host
if url:
    existing["HUB_PUBLIC_URL"] = url.rstrip("/")
lines = []
if path.is_file():
    seen = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "=" in raw and not raw.lstrip().startswith("#"):
            k = raw.split("=", 1)[0].strip()
            if k in existing:
                lines.append(f"{k}={existing[k]}")
                seen.add(k)
                continue
        lines.append(raw)
    for k, v in existing.items():
        if k not in seen and k in {"HUB_PUBLIC_HOST", "HUB_PUBLIC_URL"}:
            lines.append(f"{k}={v}")
else:
    lines = [f"{k}={v}" for k, v in existing.items() if v]
path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
PY
fi

if [[ ! -f "$ROOT/.env" && ! -f "$ROOT/tokens.local.json" ]]; then
  echo "No role tokens yet. Generating gitignored board/.env ..."
  uv run "$REPO/scripts/board_gen_tokens.py" --dir "$ROOT" --print
else
  uv run "$REPO/scripts/board_gen_tokens.py" --dir "$ROOT"
fi

uv run "$REPO/scripts/hub_ensure_bootstrap.py" --dir "$ROOT"
uv run "$REPO/scripts/hub_build_pack.py" --dir "$ROOT" --repo "$REPO"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

HOST="${BOARD_HOST:-0.0.0.0}"
if [[ -n "${PORT:-}" ]]; then
  PORT="$PORT"
else
  PORT="${BOARD_PORT:-8787}"
fi
PUBLIC="${HUB_PUBLIC_URL:-http://127.0.0.1:${PORT}}"
PUBLIC="${PUBLIC%/}"

echo "Job Hub → http://${HOST}:${PORT}/  (process bind)"
echo "Public origin: ${PUBLIC}  (invites, signup, onboarding)"
echo "Gitignored secrets: ${ROOT}/.env ${ROOT}/tokens.local.json"
if [[ -n "${HUB_BOOTSTRAP_TOKEN:-}" && "${HUB_BOOTSTRAP_USED:-}" != "1" ]]; then
  echo "Admin signup (one-time): ${PUBLIC}/admin/signup#bootstrap=${HUB_BOOTSTRAP_TOKEN}"
  echo "Then onboard the candidate (required): ${PUBLIC}/onboarding"
  echo "After that admin exists, /admin/signup redirects to /login."
fi
echo "Sibling agents: ${PUBLIC}/api/jobs with Bearer keys (or X-Role + X-Token compat)"
echo "Maintainer owns this process. Do not commit .env or data/*.db"

exec uv run uvicorn app.main:create_app --factory --host "$HOST" --port "$PORT"
