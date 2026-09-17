"""CatalogQuery: approved shared skills + hosted MCP names.

Unauthenticated agents list this instead of scraping git. Local drafts stay
behind SkillStore.list_visible. Maintainer still owns skill.record proctor.
"""

from __future__ import annotations

from typing import Any

from app.pack import CONNECTOR_CATALOG
from app.skill_store import SkillStore

CATALOG_NOTE = (
    "Always use registry skills and MCPs. If you use something outside this "
    "catalog, register it (POST /api/registry/recordings or a local skill) and "
    "store a memory fact. Maintainer owns skill.record proctor."
)


def catalog_skill(row: dict[str, Any]) -> dict[str, Any]:
    """Compact public row. No markdown body, no owner id."""
    return {
        "slug": row["slug"],
        "name": row["name"],
        "kind": row.get("kind") or "skill",
        "role": row["role"],
        "tags": list(row.get("tags") or []),
        "scope": "shared",
        "status": "approved",
        "platform": row.get("platform") or "",
        "origin": row.get("origin") or "",
    }


def hosted_mcps() -> list[dict[str, str]]:
    return [
        {
            "id": str(row["id"]),
            "hosted": str(row["hosted"]),
            "reason": str(row["reason"]),
        }
        for row in CONNECTOR_CATALOG
    ]


def public_catalog(
    store: SkillStore,
    *,
    tag: str | None = None,
    role: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    skills = store.list_approved_shared(tag=tag, role=role, limit=limit)
    compact = [catalog_skill(item) for item in skills]
    mcps = hosted_mcps()
    return {
        "skills": compact,
        "mcps": mcps,
        "count": len(compact),
        "mcp_count": len(mcps),
        "registry": "/api/registry/skills",
        "note": CATALOG_NOTE,
    }
