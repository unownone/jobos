#!/usr/bin/env bash
# Stop the retired self-hosted Actions runner and git-fetch deploy watcher.
# Production is GHCR + SSH from GitHub-hosted Actions (docs/deploy.md).
set -euo pipefail

echo "Disabling legacy self-hosted deploy units (if present)…"

disable_unit() {
  local unit="$1"
  if systemctl list-unit-files "$unit" >/dev/null 2>&1; then
    sudo systemctl disable --now "$unit" 2>/dev/null || true
    echo "  disabled $unit"
  fi
  if systemctl --user status >/dev/null 2>&1; then
    systemctl --user disable --now "$unit" 2>/dev/null || true
  fi
}

disable_unit jobos-github-runner.service
disable_unit jobos-deploy-watch.timer
disable_unit jobos-deploy-watch.service

if [[ -x "${HOME}/actions-runner/svc.sh" ]]; then
  echo "  leftover Actions runner dir: ${HOME}/actions-runner (not deleted)"
  echo "  unregister if you want: (cd ${HOME}/actions-runner && sudo ./svc.sh uninstall) "
fi

echo "Legacy units disabled. New path: merge to main → Release → SSH pull GHCR tag."
