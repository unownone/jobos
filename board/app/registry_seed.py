"""Seed Hub skill + MCP registries from git. Agents read the DB, not the files.

On Hub boot, pack rebuild, POST /api/registry/seed, and schema migrate (tables
created; rows filled on first app start / explicit seed):

- skills: GitHub starters (`skills/*/SKILL.md`, `skills/starters/*.yaml`) plus
  adopted in-repo SKILL.md paths from `skills/lists/adopted.yaml`.
- mcps: `skills/lists/` (adopted / wanted / rejected) merged with
  `mcp/mcp.example.json` and `mcp/hosted/*.json`.

Upsert is by stable slug (`skl_{slug}` / `mcp_{slug}` on first insert). Restart
does not duplicate. origin=github only; this path never promotes local forks
or consumes `skill.record` (maintainer/admin proctor only).

If an agent uses a skill or MCP that is not in these tables, register it
(local skill / recording, or tell maintainer to add the list row) and write a
durable Hub memory fact (`catalog_note` / `tool_failure`) so the next bot does
not rediscover it from git alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.mcp_seed import seed_github_mcps
from app.skill_seed import seed_github_skills
from app.settings import Settings


def seed_hub_registries(
    db: Any,
    repo_root: Path | None = None,
    *,
    settings: Settings | None = None,
) -> dict[str, dict[str, int]]:
    return {
        "skills": seed_github_skills(db, repo_root, settings=settings),
        "mcps": seed_github_mcps(db, repo_root, settings=settings),
    }
