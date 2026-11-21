#!/usr/bin/env bash
# Deploy Job Hub as the Go API. It serves the built React SPA when web/dist exists.
# Default listen address is 0.0.0.0:8787. Docker is optional and not required.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# JOBHUB_BOARD_DIR is the secrets/data dir (defaults to board/) so tests can isolate .env.
BOARD="${JOBHUB_BOARD_DIR:-$REPO/board}"
export PATH="$HOME/.local/bin:$PATH"

if ! command -v openssl >/dev/null 2>&1; then
  echo "hub_deploy: openssl is required to mint local tokens" >&2
  exit 1
fi

export BOARD_HOST="${BOARD_HOST:-0.0.0.0}"
export BOARD_PORT="${BOARD_PORT:-8787}"
export HUB_ADDR="${HUB_ADDR:-${BOARD_HOST}:${BOARD_PORT}}"
export HUB_REPO_ROOT="${HUB_REPO_ROOT:-$REPO}"
export HUB_WEB_ROOT="${HUB_WEB_ROOT:-$REPO/web/dist}"
export HUB_PLUGINS="${HUB_PLUGINS:-off}"

echo "Job Hub deploy"
echo "  bind: ${HUB_ADDR}"
echo "  gitignored secrets: ${BOARD}/.env ${BOARD}/tokens.local.json"
echo "  postgres: ${DATABASE_URL:-set DATABASE_URL}"
if [[ -n "${HUB_PUBLIC_URL:-}" ]]; then
  echo "  public url: ${HUB_PUBLIC_URL}"
fi

prepare_secrets() {
  local env_file="$BOARD/.env"
  local json_file="$BOARD/tokens.local.json"
  mkdir -p "$BOARD"
  declare -A envmap=()
  local line key value
  if [[ -f "$env_file" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
      key="${line%%=*}"
      value="${line#*=}"
      value="${value%\"}"
      value="${value#\"}"
      value="${value%\'}"
      value="${value#\'}"
      envmap["$key"]="$value"
    done < "$env_file"
  fi
  local roles=(discovery apply outreach admin maintenance)
  local token_keys=(BOARD_TOKEN_DISCOVERY BOARD_TOKEN_APPLY BOARD_TOKEN_OUTREACH BOARD_TOKEN_ADMIN BOARD_TOKEN_MAINTENANCE)
  local i token_key
  for i in "${!roles[@]}"; do
    token_key="${token_keys[$i]}"
    if [[ -z "${envmap[$token_key]:-}" ]]; then
      envmap["$token_key"]="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n=')"
    fi
  done
  local token="${HUB_BOOTSTRAP_TOKEN:-${envmap[HUB_BOOTSTRAP_TOKEN]:-}}"
  local used="${envmap[HUB_BOOTSTRAP_USED]:-}"
  local public="${HUB_PUBLIC_URL:-http://${BOARD_HOST}:${BOARD_PORT}}"
  public="${public%/}"
  if [[ "$used" == "1" ]]; then
    echo "admin already bootstrapped; bootstrap token disabled"
  else
    if [[ -z "$token" ]]; then
      token="jh_boot_$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n=')"
    elif [[ "$token" != jh_boot_* ]]; then
      token="jh_boot_${token}"
    fi
    envmap[HUB_BOOTSTRAP_TOKEN]="$token"
    echo "Admin signup: ${public}/admin/signup#bootstrap=${token}"
  fi
  {
    echo "# Generated locally — DO NOT COMMIT"
    echo "BOARD_HOST=${envmap[BOARD_HOST]:-$BOARD_HOST}"
    echo "BOARD_PORT=${envmap[BOARD_PORT]:-$BOARD_PORT}"
    echo "BOARD_DB=${envmap[BOARD_DB]:-data/board.db}"
    for token_key in "${token_keys[@]}"; do
      echo "${token_key}=${envmap[$token_key]}"
    done
    if [[ -n "${HUB_PUBLIC_URL:-${envmap[HUB_PUBLIC_URL]:-}}" ]]; then
      echo "HUB_PUBLIC_URL=${HUB_PUBLIC_URL:-${envmap[HUB_PUBLIC_URL]}}"
    fi
    if [[ -n "${envmap[HUB_BOOTSTRAP_TOKEN]:-}" ]]; then
      echo "HUB_BOOTSTRAP_TOKEN=${envmap[HUB_BOOTSTRAP_TOKEN]}"
    fi
    if [[ "$used" == "1" ]]; then
      echo "HUB_BOOTSTRAP_USED=1"
    fi
    local reserved=" BOARD_HOST BOARD_PORT BOARD_DB BOARD_TOKEN_DISCOVERY BOARD_TOKEN_APPLY BOARD_TOKEN_OUTREACH BOARD_TOKEN_ADMIN BOARD_TOKEN_MAINTENANCE HUB_PUBLIC_URL HUB_BOOTSTRAP_TOKEN HUB_BOOTSTRAP_USED "
    for key in "${!envmap[@]}"; do
      if [[ "$reserved" != *" $key "* ]]; then
        echo "${key}=${envmap[$key]}"
      fi
    done
  } > "$env_file"
  {
    echo "{"
    echo "  \"discovery\": \"${envmap[BOARD_TOKEN_DISCOVERY]}\","
    echo "  \"apply\": \"${envmap[BOARD_TOKEN_APPLY]}\","
    echo "  \"outreach\": \"${envmap[BOARD_TOKEN_OUTREACH]}\","
    echo "  \"admin\": \"${envmap[BOARD_TOKEN_ADMIN]}\","
    echo "  \"maintenance\": \"${envmap[BOARD_TOKEN_MAINTENANCE]}\""
    if [[ -n "${envmap[HUB_BOOTSTRAP_TOKEN]:-}" ]]; then
      echo "  ,\"bootstrap\": \"${envmap[HUB_BOOTSTRAP_TOKEN]}\""
    fi
    echo "}"
  } > "$json_file"
  echo "Gitignored secrets: ${env_file} ${json_file}"
  echo "Do not commit .env or tokens.local.json."
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    if [[ -z "${!key:-}" ]]; then
      export "${key}=${value}"
    fi
  done < "$env_file"
}

prepare_secrets

if [[ "${HUB_DEPLOY_DRY_RUN:-}" == "1" ]]; then
  echo "HUB_DEPLOY_DRY_RUN=1 — not starting the Go API"
  exit 0
fi

if [[ ! -f "${HUB_WEB_ROOT}/index.html" ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "hub_deploy: npm is required to build ${HUB_WEB_ROOT}" >&2
    exit 1
  fi
  npm install --prefix "$REPO/web"
  npm run build --prefix "$REPO/web"
fi
if ! command -v go >/dev/null 2>&1; then
  echo "hub_deploy: go is required to start the API" >&2
  exit 1
fi

cd "$REPO/server"
exec go run ./cmd/hub
