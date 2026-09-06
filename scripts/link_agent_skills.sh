#!/usr/bin/env bash
# Point Claude Code (.claude/skills) and Cursor (.cursor/skills) at:
#   - in-repo OS skills under skills/*/SKILL.md
#   - agent-skills installs under .agents/skills/*/SKILL.md
# Replaces a single directory symlink (Claude Desktop sometimes skips those).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -L .claude/skills ]]; then
  rm .claude/skills
fi
mkdir -p .claude/skills .cursor/skills .agents/skills

link_skill() {
  local name="$1" target="$2"
  ln -sfn "$target" ".claude/skills/$name"
  ln -sfn "$target" ".cursor/skills/$name"
}

shopt -s nullglob
for skill_md in skills/*/SKILL.md; do
  name="$(basename "$(dirname "$skill_md")")"
  link_skill "$name" "../../skills/$name"
done
for skill_md in .agents/skills/*/SKILL.md; do
  name="$(basename "$(dirname "$skill_md")")"
  # Prefer OS skill of the same name if both exist.
  if [[ -f "skills/$name/SKILL.md" ]]; then
    continue
  fi
  link_skill "$name" "../../.agents/skills/$name"
done

echo "link_agent_skills: claude=$(find .claude/skills -maxdepth 1 -mindepth 1 | wc -l) cursor=$(find .cursor/skills -maxdepth 1 -mindepth 1 | wc -l)"
