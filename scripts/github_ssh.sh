#!/usr/bin/env bash
# Configure Git to talk to GitHub over SSH using the Job Hub deploy key.
# Default transport is ssh.github.com:443 because github.com:22 is often blocked.
#
# Source this file, then call jobos_github_ssh_apply.
# Env:
#   JOBOS_SSH_KEY           Path to the private deploy key (default: ~/.ssh/jobos_deploy)
#   JOBOS_SSH_KNOWN_HOSTS   known_hosts file (default: deploy/ssh/known_hosts)
#   JOBOS_STATE_DIR         Runtime ssh config dir (default: ~/.jobos)
set -euo pipefail

jobos_github_ssh_root() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ -f "$here/../deploy/ssh/known_hosts" ]]; then
    (cd "$here/.." && pwd)
    return
  fi
  if [[ -n "${JOBOS_REPO:-}" && -f "${JOBOS_REPO}/deploy/ssh/known_hosts" ]]; then
    printf '%s\n' "$JOBOS_REPO"
    return
  fi
  printf '%s\n' "$here"
}

jobos_github_ssh_pick_key() {
  local candidate
  for candidate in \
    "${JOBOS_SSH_KEY:-}" \
    "${HOME}/.ssh/jobos_deploy" \
    "${HOME}/.ssh/id_ed25519" \
    "${HOME}/.ssh/id_rsa"; do
    if [[ -n "$candidate" && -f "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

jobos_github_ssh_pick_known_hosts() {
  local root
  root="$(jobos_github_ssh_root)"
  local candidate
  for candidate in \
    "${JOBOS_SSH_KNOWN_HOSTS:-}" \
    "${HOME}/.jobos/ssh/known_hosts" \
    "${root}/deploy/ssh/known_hosts" \
    "${root}/ssh/known_hosts"; do
    if [[ -n "$candidate" && -f "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  echo "jobos_github_ssh: no known_hosts file found" >&2
  return 1
}

jobos_github_ssh_apply() {
  local state_dir config known key
  state_dir="${JOBOS_STATE_DIR:-${HOME}/.jobos}"
  mkdir -p "$state_dir/ssh"
  chmod 700 "$state_dir/ssh" 2>/dev/null || true
  known="$(jobos_github_ssh_pick_known_hosts)"
  cp "$known" "$state_dir/ssh/known_hosts"
  chmod 644 "$state_dir/ssh/known_hosts"
  config="$state_dir/ssh/config"
  cat > "$config" <<EOF
Host github.com
  HostName ssh.github.com
  Port 443
  User git
  IdentitiesOnly yes
  IdentityAgent none
  PreferredAuthentications publickey
  StrictHostKeyChecking yes
  HashKnownHosts no
  UserKnownHostsFile ${state_dir}/ssh/known_hosts
  GlobalKnownHostsFile /dev/null

Host ssh.github.com
  Port 443
  User git
  IdentitiesOnly yes
  IdentityAgent none
  PreferredAuthentications publickey
  StrictHostKeyChecking yes
  HashKnownHosts no
  UserKnownHostsFile ${state_dir}/ssh/known_hosts
  GlobalKnownHostsFile /dev/null
EOF
  if key="$(jobos_github_ssh_pick_key)"; then
    chmod 600 "$key" 2>/dev/null || true
    cat >> "$config" <<EOF
Host github.com
  IdentityFile ${key}
Host ssh.github.com
  IdentityFile ${key}
EOF
  fi
  chmod 600 "$config"
  export JOBOS_SSH_CONFIG="$config"
  export GIT_SSH_COMMAND="ssh -F ${config} -o BatchMode=yes"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  jobos_github_ssh_apply
  echo "GIT_SSH_COMMAND=${GIT_SSH_COMMAND}"
  echo "JOBOS_SSH_CONFIG=${JOBOS_SSH_CONFIG}"
  if key="$(jobos_github_ssh_pick_key)"; then
    echo "key=${key}"
  else
    echo "key=(none — ssh will fail until ~/.ssh/jobos_deploy exists)"
  fi
fi
