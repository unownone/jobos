"""MCP / connector registry: git lists + mcp.example.json, live in Hub SQLite."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.db import utc_now
from app.storage.repos.registry import McpRepo, apply_mcp_schema
from app.tenant import COMPAT_ACCOUNT_ID, TenantContext
from app.tenant_schema import ensure_tenant_schema

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")

MCP_KINDS = ("mcp", "http", "builtin", "local", "cli")
MCP_STATUSES = ("adopted", "wanted", "rejected")
MCP_ORIGINS = ("github", "recording", "mutation", "memory")

def ensure_mcp_schema(conn: Any) -> None:
    apply_mcp_schema(conn)
    ensure_tenant_schema(conn)


def _load(raw: str | None, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    return json.loads(raw)


def _normalize_str_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        return [text] if text else []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def content_hash_for(fields: dict[str, Any]) -> str:
    blob = json.dumps(
        {
            "slug": fields.get("slug") or "",
            "name": fields.get("name") or "",
            "kind": fields.get("kind") or "mcp",
            "status": fields.get("status") or "adopted",
            "verdict": fields.get("verdict") or "",
            "capability": list(fields.get("capability") or []),
            "roles": list(fields.get("roles") or []),
            "platforms": list(fields.get("platforms") or []),
            "source": fields.get("source") or "",
            "install": fields.get("install") or "",
            "auth": fields.get("auth") or "",
            "notes": fields.get("notes") or "",
            "reason": fields.get("reason") or "",
            "next_action": fields.get("next_action") or "",
            "config": fields.get("config") or {},
            "hosted": fields.get("hosted") or "",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def stable_mcp_id(slug: str) -> str:
    return f"mcp_{slug}"


def public_mcp(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "name": row["name"],
        "kind": row["kind"],
        "status": row["status"],
        "verdict": row.get("verdict") or "",
        "capability": list(row.get("capability") or []),
        "roles": list(row.get("roles") or []),
        "platforms": list(row.get("platforms") or []),
        "source": row.get("source") or "",
        "install": row.get("install") or "",
        "auth": row.get("auth") or "",
        "notes": row.get("notes") or "",
        "reason": row.get("reason") or "",
        "next_action": row.get("next_action") or "",
        "config": row.get("config") or {},
        "hosted": row.get("hosted") or "",
        "origin": row["origin"],
        "origin_ref": row.get("origin_ref") or "",
        "version": int(row.get("version") or 1),
        "content_hash": row["content_hash"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_mcp(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": data["id"],
        "slug": data["slug"],
        "name": data["name"],
        "kind": data["kind"],
        "status": data["status"],
        "verdict": data["verdict"] or "",
        "capability": _load(data["capability_json"], []),
        "roles": _load(data["roles_json"], []),
        "platforms": _load(data["platforms_json"], []),
        "source": data["source"] or "",
        "install": data["install"] or "",
        "auth": data["auth"] or "",
        "notes": data["notes"] or "",
        "reason": data["reason"] or "",
        "next_action": data["next_action"] or "",
        "config": _load(data["config_json"], {}),
        "hosted": data["hosted"] or "",
        "origin": data["origin"],
        "origin_ref": data["origin_ref"] or "",
        "version": int(data["version"] or 1),
        "content_hash": data["content_hash"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }


def mcp_matches_query(
    item: dict[str, Any],
    *,
    status: str | None = None,
    kind: str | None = None,
    role: str | None = None,
    capability: str | None = None,
    platform: str | None = None,
) -> bool:
    if status and item.get("status") != status:
        return False
    if kind and item.get("kind") != kind:
        return False
    if role:
        roles = [str(r).lower() for r in item.get("roles") or []]
        if role.lower() not in roles and "all" not in roles:
            return False
    if capability:
        caps = [str(c).lower() for c in item.get("capability") or []]
        if capability.lower() not in caps:
            return False
    if platform:
        plats = [str(p).lower() for p in item.get("platforms") or []]
        if platform.lower() not in plats:
            return False
    return True


class McpStore:
    def __init__(self, db: Any, tenant: TenantContext | None = None) -> None:
        self.db = db
        self.tenant = tenant or TenantContext(COMPAT_ACCOUNT_ID)
        ensure_mcp_schema(self.db.conn)
        self.db.conn.commit()
        self.repo = McpRepo(self.db.conn)

    @property
    def account_id(self) -> str:
        return self.tenant.account_id

    def get(self, mcp_id: str) -> dict[str, Any] | None:
        row = self.repo.get(self.account_id, mcp_id)
        return row_to_mcp(row) if row else None

    def get_by_slug(self, slug: str) -> dict[str, Any] | None:
        row = self.repo.get_by_slug(self.account_id, slug)
        return row_to_mcp(row) if row else None

    def get_by_id_or_slug(self, key: str) -> dict[str, Any] | None:
        found = self.get(key)
        if found is not None:
            return found
        return self.get_by_slug(key)

    def list_visible(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        role: str | None = None,
        capability: str | None = None,
        platform: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        rows = self.repo.list_mcps(self.account_id, limit)
        out: list[dict[str, Any]] = []
        for row in rows:
            item = row_to_mcp(row)
            if mcp_matches_query(
                item,
                status=status,
                kind=kind,
                role=role,
                capability=capability,
                platform=platform,
            ):
                out.append(item)
        return out

    def insert(self, fields: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        now = utc_now()
        slug = str(fields["slug"]).strip().lower()
        if not SLUG_RE.match(slug):
            raise ValueError("mcp slug is invalid")
        mcp_id = fields.get("id") or f"mcp_{slug}"
        kind = str(fields.get("kind") or "mcp")
        if kind not in MCP_KINDS:
            raise ValueError(f"unknown mcp kind {kind!r}")
        status = str(fields.get("status") or "adopted")
        if status not in MCP_STATUSES:
            raise ValueError(f"unknown mcp status {status!r}")
        origin = str(fields.get("origin") or "github")
        if origin not in MCP_ORIGINS:
            origin = "github"
        digest = fields.get("content_hash") or content_hash_for({**fields, "slug": slug})
        self.repo.insert_mcp(
            self.account_id,
            {
                "id": mcp_id,
                "slug": slug,
                "name": fields["name"],
                "kind": kind,
                "status": status,
                "verdict": fields.get("verdict") or "",
                "capability": _normalize_str_list(fields.get("capability")),
                "roles": _normalize_str_list(fields.get("roles")),
                "platforms": _normalize_str_list(fields.get("platforms")),
                "source": fields.get("source") or "",
                "install": fields.get("install") or "",
                "auth": fields.get("auth") or "",
                "notes": fields.get("notes") or "",
                "reason": fields.get("reason") or "",
                "next_action": fields.get("next_action") or "",
                "config": fields.get("config") or {},
                "hosted": fields.get("hosted") or "",
                "origin": origin,
                "origin_ref": fields.get("origin_ref") or "",
                "version": int(fields.get("version") or 1),
                "content_hash": digest,
                "created_at": fields.get("created_at") or now,
                "updated_at": fields.get("updated_at") or now,
            },
        )
        if commit:
            self.db.conn.commit()
        stored = self.get(mcp_id)
        if stored is None:
            raise RuntimeError("mcp insert did not persist")
        return stored

    def update(self, mcp_id: str, fields: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        current = self.get(mcp_id)
        if current is None:
            raise KeyError(mcp_id)
        merged = dict(current)
        merged.update(fields)
        merged["content_hash"] = content_hash_for(merged)
        now = utc_now()
        self.repo.update_mcp(self.account_id, mcp_id, merged, updated_at=now)
        if commit:
            self.db.conn.commit()
        stored = self.get(mcp_id)
        if stored is None:
            raise KeyError(mcp_id)
        return stored

    def upsert_github(self, fields: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """Seed or refresh a git-authored MCP. Never overwrite non-github origin rows."""
        slug = str(fields["slug"]).strip().lower()
        existing = self.get_by_slug(slug)
        payload = {
            **fields,
            "id": fields.get("id") or f"mcp_{slug}",
            "slug": slug,
            "origin": "github",
        }
        payload["content_hash"] = content_hash_for(payload)
        if existing is None:
            stored = self.insert(payload)
            return stored, "inserted"
        if existing.get("origin") != "github":
            return existing, "skipped"
        if existing.get("content_hash") == payload["content_hash"]:
            return existing, "unchanged"
        updated = self.update(
            existing["id"],
            {
                "name": payload["name"],
                "kind": payload.get("kind") or "mcp",
                "status": payload.get("status") or "adopted",
                "verdict": payload.get("verdict") or "",
                "capability": payload.get("capability") or [],
                "roles": payload.get("roles") or [],
                "platforms": payload.get("platforms") or [],
                "source": payload.get("source") or "",
                "install": payload.get("install") or "",
                "auth": payload.get("auth") or "",
                "notes": payload.get("notes") or "",
                "reason": payload.get("reason") or "",
                "next_action": payload.get("next_action") or "",
                "config": payload.get("config") or {},
                "hosted": payload.get("hosted") or "",
                "origin_ref": payload.get("origin_ref") or "",
                "version": int(existing.get("version") or 1) + 1,
            },
        )
        return updated, "updated"
