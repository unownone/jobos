#!/usr/bin/env bash
# Offline checks for GitHub SSH deploy-key wiring. No secrets, no network required
# except an optional live probe when JOBOS_SSH_LIVE=1 and a key is present.
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

echo "github_ssh_selftest"
check test -f deploy/ssh/known_hosts
check test -f deploy/ssh/config
check test -x scripts/github_ssh.sh
check test -x scripts/install_github_ssh.sh
check test -x scripts/hub_host_deploy.sh
check test -x scripts/jobos_deploy_watch.sh

echo "bash -n"
bash -n scripts/github_ssh.sh
bash -n scripts/install_github_ssh.sh
bash -n scripts/hub_host_deploy.sh
bash -n scripts/jobos_deploy_watch.sh
bash -n scripts/install_host_services.sh
bash -n scripts/github_ssh_selftest.sh
echo "ok: bash -n deploy scripts"

echo "known_hosts fingerprints (must match GitHub docs)"
mapfile -t fps < <(ssh-keygen -l -f deploy/ssh/known_hosts | awk '{print $2}' | sort -u)
want_ed25519="SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU"
want_ecdsa="SHA256:p2QAMXNIC1TJYWeIOttrVc98/R1BUFWu3/LiyKgUfQM"
want_rsa="SHA256:uNiVztksCsDhcc0u9e8BujQXVUpKZIDTMczCvj3tD2s"
printf '%s\n' "${fps[@]}"
echo "${fps[@]}" | grep -Fq "$want_ed25519" || { echo "FAIL: missing GitHub ED25519 fingerprint" >&2; fail=1; }
echo "${fps[@]}" | grep -Fq "$want_ecdsa" || { echo "FAIL: missing GitHub ECDSA fingerprint" >&2; fail=1; }
echo "${fps[@]}" | grep -Fq "$want_rsa" || { echo "FAIL: missing GitHub RSA fingerprint" >&2; fail=1; }

check_host() {
  local pattern="$1"
  local label="$2"
  if grep -E "$pattern" deploy/ssh/known_hosts >/dev/null; then
    echo "ok: known_hosts has ${label}"
  else
    echo "FAIL: known_hosts missing ${label}" >&2
    fail=1
  fi
}
check_host '^github\.com ' "github.com"
check_host '^ssh\.github\.com ' "ssh.github.com"
check_host '^\[ssh\.github\.com\]:443 ' "[ssh.github.com]:443"

if grep -q "HostName ssh.github.com" deploy/ssh/config && grep -q "Port 443" deploy/ssh/config; then
  echo "ok: ssh config uses ssh.github.com:443"
else
  echo "FAIL: deploy/ssh/config must pin ssh.github.com port 443" >&2
  fail=1
fi

# Runtime config must pin 443 and known_hosts even without a private key.
tmp_home="$(mktemp -d)"
trap 'rm -rf "$tmp_home"' EXIT
export HOME="$tmp_home"
export JOBOS_STATE_DIR="$tmp_home/.jobos"
unset JOBOS_SSH_KEY || true
# shellcheck source=github_ssh.sh
source "$ROOT/scripts/github_ssh.sh"
jobos_github_ssh_apply
test -f "$JOBOS_SSH_CONFIG"
grep -q "Port 443" "$JOBOS_SSH_CONFIG"
grep -q "HostName ssh.github.com" "$JOBOS_SSH_CONFIG"
grep -q "UserKnownHostsFile" "$JOBOS_SSH_CONFIG"
[[ "$GIT_SSH_COMMAND" == ssh\ -F\ * ]]
echo "ok: jobos_github_ssh_apply wrote runtime config"
echo "GIT_SSH_COMMAND=$GIT_SSH_COMMAND"

if [[ "${JOBOS_SSH_LIVE:-}" == "1" ]] && jobos_github_ssh_pick_key >/dev/null; then
  echo "live SSH probe"
  set +e
  ssh -F "$JOBOS_SSH_CONFIG" -o BatchMode=yes -o ConnectTimeout=10 -T git@github.com
  rc=$?
  set -e
  if [[ "$rc" -eq 1 ]]; then
    echo "ok: GitHub SSH auth (exit 1 is success for ssh -T)"
    git ls-remote git@github.com:unownone/jobos.git HEAD
    echo "ok: git ls-remote over SSH"
  else
    echo "FAIL: live SSH probe exit $rc" >&2
    fail=1
  fi
else
  echo "skip: live SSH probe (set JOBOS_SSH_LIVE=1 and provide ~/.ssh/jobos_deploy)"
fi

if [[ "$fail" -ne 0 ]]; then
  echo "github_ssh_selftest: FAILED" >&2
  exit 1
fi
echo "github_ssh_selftest: passed"
