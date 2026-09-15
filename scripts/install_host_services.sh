#!/usr/bin/env bash
# Install host systemd units: deploy-on-main watcher (+ optional Actions runner).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="${JOBOS_SYSTEMD_DIR:-/etc/systemd/system}"
STATE_DIR="${HOME}/.jobos"
mkdir -p "$STATE_DIR"

install -m 0755 "$ROOT/scripts/hub_host_deploy.sh" "$STATE_DIR/hub_host_deploy.sh"
install -m 0755 "$ROOT/scripts/jobos_deploy_watch.sh" "$STATE_DIR/jobos_deploy_watch.sh"
install -m 0755 "$ROOT/scripts/github_ssh.sh" "$STATE_DIR/github_ssh.sh"
install -d -m 0700 "$STATE_DIR/ssh"
install -m 0644 "$ROOT/deploy/ssh/known_hosts" "$STATE_DIR/ssh/known_hosts"
install -m 0600 "$ROOT/deploy/ssh/config" "$STATE_DIR/ssh/config.template"
if [[ -x "$ROOT/scripts/install_github_ssh.sh" ]]; then
  bash "$ROOT/scripts/install_github_ssh.sh" || echo "install_github_ssh: config installed; add ~/.ssh/jobos_deploy if SSH auth failed"
fi

sudo install -m 0644 "$ROOT/deploy/systemd/jobos-deploy-watch.service" "$UNIT_DIR/jobos-deploy-watch.service"
sudo install -m 0644 "$ROOT/deploy/systemd/jobos-deploy-watch.timer" "$UNIT_DIR/jobos-deploy-watch.timer"
sudo install -m 0644 "$ROOT/deploy/systemd/jobos-github-runner.service" "$UNIT_DIR/jobos-github-runner.service"
sudo systemctl daemon-reload
sudo systemctl enable --now jobos-deploy-watch.timer

if [[ -x "${HOME}/actions-runner/run.sh" && -f "${HOME}/actions-runner/.runner" ]]; then
  sudo systemctl enable --now jobos-github-runner.service
else
  echo "GitHub runner not configured yet. After scripts/install_github_runner.sh:"
  echo "  sudo systemctl enable --now jobos-github-runner.service"
fi

systemctl list-timers jobos-deploy-watch.timer --no-pager
echo "Host deploy units installed. Watcher script: $STATE_DIR/jobos_deploy_watch.sh"
