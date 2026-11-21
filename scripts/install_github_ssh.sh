#!/usr/bin/env bash
# Install GitHub SSH-over-443 config and (optional) a deploy private key.
# Does not print key material. Run on the Job Hub host as the deploy user (opc).
#
#   bash scripts/install_github_ssh.sh
#   bash scripts/install_github_ssh.sh --key-file /path/to/jobos_deploy
#   cat jobos_deploy | bash scripts/install_github_ssh.sh --key-stdin
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="${JOBOS_STATE_DIR:-${HOME}/.jobos}"
SSH_DIR="${HOME}/.ssh"
KEY_PATH="${JOBOS_SSH_KEY:-${SSH_DIR}/jobos_deploy}"
KEY_FILE=""
KEY_STDIN=0

usage() {
  cat <<'EOF'
Usage: install_github_ssh.sh [--key-file PATH] [--key-stdin]

Install ~/.jobos/ssh/{config,known_hosts} so git fetch/push to GitHub uses
ssh.github.com:443 and the Job Hub deploy key (~/.ssh/jobos_deploy).

  --key-file PATH  Copy this private key to ~/.ssh/jobos_deploy (mode 600)
  --key-stdin      Read the private key from stdin (do not log it)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --key-file)
      KEY_FILE="${2:-}"
      shift 2
      ;;
    --key-stdin) KEY_STDIN=1; shift ;;
    *)
      echo "install_github_ssh: unknown arg: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

mkdir -p "$SSH_DIR" "$STATE_DIR/ssh"
chmod 700 "$SSH_DIR"

if [[ -n "$KEY_FILE" ]]; then
  if [[ ! -f "$KEY_FILE" ]]; then
    echo "install_github_ssh: --key-file not found: $KEY_FILE" >&2
    exit 1
  fi
  cp "$KEY_FILE" "$KEY_PATH"
fi
if [[ "$KEY_STDIN" == "1" ]]; then
  cat > "$KEY_PATH"
fi
if [[ -f "$KEY_PATH" ]]; then
  chmod 600 "$KEY_PATH"
  if ! ssh-keygen -y -f "$KEY_PATH" >/dev/null 2>&1; then
    echo "install_github_ssh: $KEY_PATH is not a usable OpenSSH private key" >&2
    exit 1
  fi
  ssh-keygen -l -f "$KEY_PATH"
fi

cp "$ROOT/deploy/ssh/known_hosts" "$STATE_DIR/ssh/known_hosts"
chmod 644 "$STATE_DIR/ssh/known_hosts"
# Keep a copy next to the user key so ad-hoc ssh also verifies GitHub.
cp "$STATE_DIR/ssh/known_hosts" "$SSH_DIR/github_known_hosts"
chmod 644 "$SSH_DIR/github_known_hosts"

MARKER_BEGIN="# BEGIN JOBOS GITHUB SSH"
MARKER_END="# END JOBOS GITHUB SSH"
user_config="${SSH_DIR}/config"
touch "$user_config"
chmod 600 "$user_config"
if grep -q "$MARKER_BEGIN" "$user_config"; then
  tmp="$(mktemp)"
  skipping=0
  found=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == "$MARKER_BEGIN"* ]]; then
      skipping=1
      found=1
      continue
    fi
    if [[ "$skipping" -eq 1 && "$line" == "$MARKER_END"* ]]; then
      skipping=0
      continue
    fi
    if [[ "$skipping" -eq 0 ]]; then
      printf '%s\n' "$line" >>"$tmp"
    fi
  done <"$user_config"
  if [[ "$found" -ne 1 ]]; then
    echo "marker begin not paired" >&2
    rm -f "$tmp"
    exit 1
  fi
  mv "$tmp" "$user_config"
  chmod 600 "$user_config"
fi

{
  echo "$MARKER_BEGIN"
  echo "Include ${STATE_DIR}/ssh/config"
  echo "$MARKER_END"
} >> "$user_config"

# shellcheck source=github_ssh.sh
source "$ROOT/scripts/github_ssh.sh"
jobos_github_ssh_apply

echo "GitHub SSH config: $JOBOS_SSH_CONFIG"
echo "Testing ssh.github.com:443 (BatchMode)…"
set +e
ssh -F "$JOBOS_SSH_CONFIG" -o BatchMode=yes -o ConnectTimeout=10 -T git@github.com
ssh_rc=$?
set -e
# GitHub returns 1 on successful auth ("Hi …"), 255 on failure.
if [[ "$ssh_rc" -eq 1 ]]; then
  echo "SSH auth to GitHub succeeded."
elif [[ -f "$KEY_PATH" ]]; then
  echo "install_github_ssh: SSH auth failed (exit $ssh_rc). Check the deploy key is on the repo and has the matching public key." >&2
  exit 1
else
  echo "No ~/.ssh/jobos_deploy yet — config is installed. Re-run with --key-file after placing the key."
fi
