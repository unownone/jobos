#!/usr/bin/env bash
# Install host files for GHCR image apply. Does not register a self-hosted runner.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="${HOME}/.jobos"
DEPLOY_DIR="${JOBOS_DEPLOY_DIR:-${HOME}/jobos}"
mkdir -p "$STATE_DIR" "$DEPLOY_DIR/traefik"

install -m 0755 "$ROOT/scripts/hub_apply_image.sh" "$STATE_DIR/hub_apply_image.sh"
install -m 0755 "$ROOT/scripts/hub_host_deploy.sh" "$STATE_DIR/hub_host_deploy.sh"
install -m 0755 "$ROOT/scripts/hub_apply_image.sh" "$DEPLOY_DIR/hub_apply_image.sh"
install -m 0644 "$ROOT/deploy/compose.yml" "$DEPLOY_DIR/compose.yml"
install -m 0644 "$ROOT/traefik/traefik.yml" "$DEPLOY_DIR/traefik/traefik.yml"
install -m 0644 "$ROOT/traefik/dynamic.yml" "$DEPLOY_DIR/traefik/dynamic.yml"
install -m 0755 "$ROOT/scripts/jobos_deploy_watch.sh" "$STATE_DIR/jobos_deploy_watch.sh"
install -m 0755 "$ROOT/scripts/disable_legacy_selfhosted_deploy.sh" \
  "$STATE_DIR/disable_legacy_selfhosted_deploy.sh"

if [[ -x "$ROOT/scripts/disable_legacy_selfhosted_deploy.sh" ]]; then
  bash "$ROOT/scripts/disable_legacy_selfhosted_deploy.sh" || true
fi

echo "Host apply dir: $DEPLOY_DIR"
echo "Compose pulls JOBOS_IMAGE from GHCR. Do not clone this repo onto the box for deploys."
echo "GitHub-hosted Actions SSHs in after each GitHub Release (docs/deploy.md)."
