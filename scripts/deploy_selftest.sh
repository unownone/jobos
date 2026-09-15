#!/usr/bin/env bash
# Offline checks for GHCR release + SSH host deploy. No secrets, no network
# required except the optional live GitHub SSH probe in github_ssh_selftest.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail=0
check() {
  if "$@"; then
    echo "ok: $*"
  else
    echo "FAIL: $*" >&2
    fail=1
  fi
}

echo "deploy_selftest"

check test -f deploy/compose.yml
check test -f traefik/traefik.yml
check test -f traefik/dynamic.yml
check test -f .github/workflows/release.yml
check test -f .github/workflows/deploy.yml
check test -x scripts/jobos_release_tag.sh
check test -x scripts/hub_apply_image.sh
check test -x scripts/hub_remote_deploy.sh
check test -x scripts/hub_host_deploy.sh

echo "bash -n"
bash -n scripts/jobos_release_tag.sh
bash -n scripts/hub_apply_image.sh
bash -n scripts/hub_remote_deploy.sh
bash -n scripts/hub_host_deploy.sh
bash -n scripts/deploy_selftest.sh
echo "ok: bash -n new deploy scripts"

echo "workflows must use GitHub-hosted runners (no self-hosted)"
if grep -nE 'runs-on:[[:space:]]*\[self-hosted|runs-on:[[:space:]]*self-hosted' .github/workflows/*.yml; then
  echo "FAIL: a workflow still uses runs-on: self-hosted" >&2
  fail=1
else
  echo "ok: no runs-on: self-hosted"
fi
while IFS= read -r line; do
  echo "  $line"
  case "$line" in
    *"ubuntu-latest"*|*"ubuntu-24.04"*|*"ubuntu-24.04-arm"*|*"\${{ matrix.runner }}"*)
      ;;
    *)
      echo "FAIL: unexpected runs-on: $line" >&2
      fail=1
      ;;
  esac
done < <(grep -hE '^\s+runs-on:' .github/workflows/*.yml)

echo "production compose pulls a GHCR image and does not build on the host"
if grep -q 'image: ${JOBOS_IMAGE:-ghcr.io/unownone/jobos' deploy/compose.yml \
  || grep -q 'image: ${JOBOS_IMAGE:-ghcr.io/' deploy/compose.yml; then
  echo "ok: deploy/compose.yml uses JOBOS_IMAGE / ghcr.io"
else
  echo "FAIL: deploy/compose.yml must set image: \${JOBOS_IMAGE:-ghcr.io/...}" >&2
  fail=1
fi
if grep -qE '^[[:space:]]+build:' deploy/compose.yml; then
  echo "FAIL: deploy/compose.yml must not build from source" >&2
  fail=1
else
  echo "ok: deploy/compose.yml has no build:"
fi
if grep -q 'name: jobos' deploy/compose.yml; then
  echo "ok: compose project name jobos (keeps volume jobos_hub-data)"
else
  echo "FAIL: deploy/compose.yml must keep name: jobos" >&2
  fail=1
fi

echo "release tag format"
tag="$(bash scripts/jobos_release_tag.sh abcdef1234567890 2026.09.15)"
if [[ "$tag" == "v2026.09.15-abcdef1" ]]; then
  echo "ok: jobos_release_tag.sh → $tag"
else
  echo "FAIL: jobos_release_tag.sh produced $tag" >&2
  fail=1
fi
if bash scripts/jobos_release_tag.sh not-a-sha >/dev/null 2>&1; then
  echo "FAIL: jobos_release_tag.sh accepted a non-SHA" >&2
  fail=1
else
  echo "ok: jobos_release_tag.sh rejects non-SHA"
fi

echo "remote deploy dry-run"
out="$(JOBOS_DEPLOY_DRY_RUN=1 bash scripts/hub_remote_deploy.sh v2026.09.15-abcdef1)"
echo "$out" | grep -q 'ghcr.io/unownone/jobos:v2026.09.15-abcdef1' || {
  echo "FAIL: dry-run did not mention the GHCR image" >&2
  fail=1
}
echo "$out" | grep -q 'dry-run: would scp compose.yml' || {
  echo "FAIL: dry-run did not say it would copy compose, not the tree" >&2
  fail=1
}
echo "ok: hub_remote_deploy.sh dry-run"

echo "release workflow publishes GHCR then creates a GitHub Release"
check grep -q 'gh release create' .github/workflows/release.yml
check grep -q 'push-by-digest=true' .github/workflows/release.yml
check grep -q 'release:' .github/workflows/deploy.yml
check grep -q 'hub_remote_deploy.sh' .github/workflows/deploy.yml

echo "github_ssh_selftest (offline)"
bash scripts/github_ssh_selftest.sh

if [[ "$fail" -ne 0 ]]; then
  echo "deploy_selftest: FAILED" >&2
  exit 1
fi
echo "deploy_selftest: passed"
