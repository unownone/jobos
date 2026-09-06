#!/usr/bin/env bash
# Install curated third-party Agent Skills into .agents/skills (npx skills).
# OS skills stay in skills/. Then relink Claude/Cursor.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Directory (not a symlink) so `npx skills add` can create per-skill links.
if [[ -L .claude/skills ]]; then
  rm .claude/skills
fi
mkdir -p .claude .claude/skills .cursor/skills .agents/skills

npx --yes skills add anthropics/knowledge-work-plugins \
  --skill compose-outreach --skill draft-outreach \
  --agent cursor --agent claude-code \
  -y

npx --yes skills add microsoft/playwright-cli \
  --skill playwright-cli \
  --agent cursor --agent claude-code \
  -y

bash "$ROOT/scripts/link_agent_skills.sh"
echo "install_agent_skills: done"
