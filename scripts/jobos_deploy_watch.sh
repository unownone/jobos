#!/usr/bin/env bash
# Retired: outbound git-fetch watcher. Production deploy is GHCR tag + SSH
# from GitHub-hosted Actions (docs/deploy.md). This script is a no-op so an
# old timer cannot rebuild from a live git clone and overwrite a GHCR apply.
set -euo pipefail

echo "jobos-deploy-watch: retired."
echo "Disable this timer: sudo systemctl disable --now jobos-deploy-watch.timer"
echo "Ship path: merge to main → GitHub Release → Actions SSH → docker pull GHCR tag."
if [[ -f "${HOME}/.jobos/deployed.tag" ]]; then
  echo "last applied tag: $(tr -d '[:space:]' < "${HOME}/.jobos/deployed.tag")"
fi
exit 0
