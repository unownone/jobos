#!/usr/bin/env bash
# Retired. Job Hub deploy no longer uses a self-hosted Actions runner.
# Merge to main publishes GHCR + a GitHub Release; Deploy SSHs from ubuntu-latest.
# See docs/deploy.md. Set JOBOS_ALLOW_SELF_HOSTED_RUNNER=1 to force this script.
set -euo pipefail

if [[ "${JOBOS_ALLOW_SELF_HOSTED_RUNNER:-}" != "1" ]]; then
  cat >&2 <<'EOF'
install_github_runner: self-hosted runners are retired.

  Merge to main → .github/workflows/release.yml (GHCR + GitHub Release)
  Release       → .github/workflows/deploy.yml  (GitHub-hosted SSH + docker pull)

  bash scripts/disable_legacy_selfhosted_deploy.sh
  docs: docs/deploy.md
EOF
  exit 1
fi


REPO_SLUG="${JOBOS_GITHUB_REPO:-unownone/jobos}"
RUNNER_DIR="${JOBOS_RUNNER_DIR:-${HOME}/actions-runner}"
RUNNER_VERSION="${JOBOS_RUNNER_VERSION:-2.337.0}"
LABELS="${JOBOS_RUNNER_LABELS:-jobos,linux,ARM64}"
NAME="${JOBOS_RUNNER_NAME:-$(hostname)-jobos}"

if [[ -f "${HOME}/.jobos/deploy.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "${HOME}/.jobos/deploy.env"
  set +a
fi

token="${RUNNER_TOKEN:-${JOBOS_RUNNER_TOKEN:-}}"
if [[ -z "$token" && -f "${HOME}/.jobos/runner.token" ]]; then
  token="$(tr -d '[:space:]' < "${HOME}/.jobos/runner.token")"
fi
if [[ -z "$token" ]] && command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  token="$(gh api -X POST "repos/${REPO_SLUG}/actions/runners/registration-token" --jq .token)"
fi
if [[ -z "$token" ]]; then
  cat >&2 <<EOF
install_github_runner: need a registration token.

  gh auth login
  bash scripts/install_github_runner.sh

Or paste a token from
  https://github.com/${REPO_SLUG}/settings/actions/runners/new
into \$HOME/.jobos/runner.token (single line) and re-run.
EOF
  exit 1
fi

mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"
if [[ ! -x ./config.sh ]]; then
  tarball="actions-runner-linux-arm64-${RUNNER_VERSION}.tar.gz"
  url="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${tarball}"
  curl -fsSL -o "$tarball" "$url"
  tar xzf "$tarball"
  rm -f "$tarball"
fi

if [[ -f .runner ]]; then
  echo "Runner already configured in $RUNNER_DIR"
else
  ./config.sh --unattended \
    --url "https://github.com/${REPO_SLUG}" \
    --token "$token" \
    --name "$NAME" \
    --labels "$LABELS" \
    --work _work \
    --replace
fi

rm -f "${HOME}/.jobos/runner.token"

# systemd user unit if lingering is on; otherwise print how to start.
if systemctl --user status >/dev/null 2>&1; then
  mkdir -p "${HOME}/.config/systemd/user"
  cat > "${HOME}/.config/systemd/user/jobos-github-runner.service" <<UNIT
[Unit]
Description=GitHub Actions runner for Job Hub host deploy
After=network-online.target

[Service]
Type=simple
WorkingDirectory=${RUNNER_DIR}
ExecStart=${RUNNER_DIR}/run.sh
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
UNIT
  systemctl --user daemon-reload
  systemctl --user enable --now jobos-github-runner.service
  echo "Runner service: systemctl --user status jobos-github-runner"
else
  echo "Start the runner with: cd $RUNNER_DIR && ./run.sh"
  echo "Or install the systemd unit from deploy/systemd/jobos-github-runner.service"
fi
