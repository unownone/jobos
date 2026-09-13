"""Skill registry: shared GitHub starters + per-bot local forks. No memory layer."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException

from app.auth import Principal
from app.bootstrap import new_id
from app.db import utc_now

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")

SKILL_ROLES = ("discovery", "apply", "outreach", "research", "maintain")
SKILL_KINDS = ("skill", "mcp", "http", "builtin")
SKILL_SCOPES = ("shared", "local")
SKILL_STATUSES = ("draft", "recorded", "proctoring", "approved", "rejected", "retired")
SKILL_ORIGINS = ("github", "recording", "mutation")
PROCTOR_STATUSES = ("none", "pending", "passed", "failed")
RECORDING_STATUSES = ("queued", "proctoring", "passed", "failed", "promoted", "declined")
MOTION_TAGS = ("source", "apply", "outreach", "research", "maintain")

SKILL_SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'skill',
    role TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    scope TEXT NOT NULL DEFAULT 'shared',
    owner_user_id TEXT,
    status TEXT NOT NULL DEFAULT 'approved',
    platform TEXT,
    match_json TEXT,
    inputs_json TEXT,
    outputs_json TEXT,
    body_md TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'github',
    origin_ref TEXT,
    parent_skill_id TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    content_hash TEXT NOT NULL,
    reproducible INTEGER NOT NULL DEFAULT 1,
    proctor_status TEXT NOT NULL DEFAULT 'none',
    proctor_note TEXT,
    proctor_evidence_json TEXT,
    approved_at TEXT,
    approved_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    created_by TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_shared_slug
    ON skills(slug) WHERE scope = 'shared';

CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_local_slug
    ON skills(owner_user_id, slug) WHERE scope = 'local';

CREATE INDEX IF NOT EXISTS idx_skills_role_status ON skills(role, status);
CREATE INDEX IF NOT EXISTS idx_skills_owner ON skills(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_skills_origin ON skills(origin);

CREATE TABLE IF NOT EXISTS skill_recordings (
    id TEXT PRIMARY KEY,
    skill_id TEXT,
    submitted_by TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    queue_item_id TEXT,
    proctor_note TEXT,
    proctor_evidence_json TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_skill_recordings_status ON skill_recordings(status);
CREATE INDEX IF NOT EXISTS idx_skill_recordings_submitter ON skill_recordings(submitted_by);
"""


def ensure_skill_schema(conn: Any) -> None:
    conn.executescript(SKILL_SCHEMA)


def owner_key(principal: Principal) -> str:
    if principal.user_id:
        return principal.user_id
    actor = principal.actor or "anon"
    return f"compat:{principal.role}:{actor}"


def is_admin(principal: Principal) -> bool:
    return principal.role == "admin" or principal.kind == "admin"


def is_maintainer(principal: Principal) -> bool:
    return is_admin(principal) or principal.role == "maintenance"


def content_hash_for(body: str, slug: str, role: str, tags: list[str]) -> str:
    blob = json.dumps(
        {"slug": slug, "role": role, "tags": tags, "body": body},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _load(raw: str | None, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    return json.loads(raw)


def _normalize_slug(slug: str) -> str:
    text = (slug or "").strip().lower()
    if not SLUG_RE.match(text):
        raise HTTPException(status_code=422, detail="slug must be lowercase letters, digits, and hyphens")
    return text


def _normalize_tags(tags: Any) -> list[str]:
    if tags is None:
        return []
    if not isinstance(tags, list):
        raise HTTPException(status_code=422, detail="tags must be a list")
    out: list[str] = []
    seen: set[str] = set()
    for item in tags:
        tag = str(item).strip().lower()
        if not tag or not TAG_RE.match(tag):
            raise HTTPException(status_code=422, detail=f"invalid tag {item!r}")
        if tag not in seen:
            seen.add(tag)
            out.append(tag)
    if not out:
        raise HTTPException(status_code=422, detail="at least one tag is required")
    return out


def _normalize_match(raw: Any) -> dict[str, list[str]]:
    if raw is None:
        return {"ats": [], "url_patterns": [], "apply_kind": []}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="match must be an object")
    extra = set(raw) - {"ats", "url_patterns", "apply_kind"}
    if extra:
        raise HTTPException(status_code=422, detail=f"unknown match keys: {sorted(extra)}")
    out: dict[str, list[str]] = {}
    for key in ("ats", "url_patterns", "apply_kind"):
        value = raw.get(key) or []
        if not isinstance(value, list):
            raise HTTPException(status_code=422, detail=f"match.{key} must be a list")
        out[key] = [str(item).strip() for item in value if str(item).strip()]
    return out


def _normalize_str_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=422, detail="expected a list of strings")
    return [str(item).strip() for item in raw if str(item).strip()]


def public_skill(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "name": row["name"],
        "kind": row["kind"],
        "role": row["role"],
        "tags": list(row.get("tags") or []),
        "scope": row["scope"],
        "owner_user_id": row.get("owner_user_id"),
        "status": row["status"],
        "platform": row.get("platform") or "",
        "match": row.get("match") or {"ats": [], "url_patterns": [], "apply_kind": []},
        "inputs": list(row.get("inputs") or []),
        "outputs": list(row.get("outputs") or []),
        "body": row.get("body") or "",
        "origin": row["origin"],
        "origin_ref": row.get("origin_ref") or "",
        "parent_skill_id": row.get("parent_skill_id"),
        "version": int(row.get("version") or 1),
        "content_hash": row["content_hash"],
        "reproducible": bool(row.get("reproducible", True)),
        "proctor_status": row.get("proctor_status") or "none",
        "proctor_note": row.get("proctor_note") or "",
        "proctor_evidence": row.get("proctor_evidence") or {},
        "approved_at": row.get("approved_at"),
        "approved_by": row.get("approved_by"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "created_by": row.get("created_by") or "",
    }


def public_recording(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "skill_id": row.get("skill_id"),
        "submitted_by": row["submitted_by"],
        "payload": row.get("payload") or {},
        "status": row["status"],
        "queue_item_id": row.get("queue_item_id"),
        "proctor_note": row.get("proctor_note") or "",
        "proctor_evidence": row.get("proctor_evidence") or {},
        "reviewed_by": row.get("reviewed_by"),
        "reviewed_at": row.get("reviewed_at"),
        "created_at": row["created_at"],
    }


def row_to_skill(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": data["id"],
        "slug": data["slug"],
        "name": data["name"],
        "kind": data["kind"],
        "role": data["role"],
        "tags": _load(data["tags_json"], []),
        "scope": data["scope"],
        "owner_user_id": data["owner_user_id"],
        "status": data["status"],
        "platform": data["platform"] or "",
        "match": _load(data["match_json"], {"ats": [], "url_patterns": [], "apply_kind": []}),
        "inputs": _load(data["inputs_json"], []),
        "outputs": _load(data["outputs_json"], []),
        "body": data["body_md"] or "",
        "origin": data["origin"],
        "origin_ref": data["origin_ref"] or "",
        "parent_skill_id": data["parent_skill_id"],
        "version": int(data["version"] or 1),
        "content_hash": data["content_hash"],
        "reproducible": bool(data["reproducible"]),
        "proctor_status": data["proctor_status"] or "none",
        "proctor_note": data["proctor_note"] or "",
        "proctor_evidence": _load(data["proctor_evidence_json"], {}),
        "approved_at": data["approved_at"],
        "approved_by": data["approved_by"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "created_by": data["created_by"] or "",
    }


def row_to_recording(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": data["id"],
        "skill_id": data["skill_id"],
        "submitted_by": data["submitted_by"],
        "payload": _load(data["payload_json"], {}),
        "status": data["status"],
        "queue_item_id": data["queue_item_id"],
        "proctor_note": data["proctor_note"] or "",
        "proctor_evidence": _load(data["proctor_evidence_json"], {}),
        "reviewed_by": data["reviewed_by"],
        "reviewed_at": data["reviewed_at"],
        "created_at": data["created_at"],
    }


def url_matches(url: str, patterns: list[str]) -> bool:
    if not url or not patterns:
        return False
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    host_path = f"{netloc}{parsed.path}".lower()
    full = url.lower()
    for raw in patterns:
        pat = str(raw).strip().lower()
        if not pat:
            continue
        stripped = pat.replace("https://", "").replace("http://", "")
        if fnmatch.fnmatch(full, pat) or fnmatch.fnmatch(host_path, stripped):
            return True
        host_pat = stripped.split("/")[0]
        if host_pat and fnmatch.fnmatch(netloc, host_pat):
            return True
    return False


def skill_matches_query(
    skill: dict[str, Any],
    *,
    tag: str | None = None,
    role: str | None = None,
    platform: str | None = None,
    ats: str | None = None,
    url: str | None = None,
    scope: str | None = None,
    status: str | None = None,
) -> bool:
    if tag and tag.lower() not in [str(t).lower() for t in skill.get("tags") or []]:
        return False
    if role and skill.get("role") != role:
        return False
    if platform and (skill.get("platform") or "").lower() != platform.lower():
        return False
    if scope and skill.get("scope") != scope:
        return False
    if status and skill.get("status") != status:
        return False
    match = skill.get("match") or {}
    if ats:
        ats_list = [str(item).lower() for item in match.get("ats") or []]
        if ats.lower() not in ats_list:
            return False
    if url:
        patterns = [str(item) for item in match.get("url_patterns") or []]
        if not url_matches(url, patterns):
            return False
    return True


def can_see_skill(principal: Principal, skill: dict[str, Any]) -> bool:
    if is_admin(principal):
        return True
    if skill.get("scope") == "shared":
        if skill.get("status") == "approved":
            return True
        return is_maintainer(principal)
    return skill.get("owner_user_id") == owner_key(principal)


def validate_skill_fields(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "slug" in payload or not partial:
        out["slug"] = _normalize_slug(str(payload.get("slug") or ""))
    if "name" in payload or not partial:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="name is required")
        out["name"] = name[:120]
    if "kind" in payload or not partial:
        kind = str(payload.get("kind") or "skill").strip()
        if kind not in SKILL_KINDS:
            raise HTTPException(status_code=422, detail=f"unknown kind {kind!r}")
        out["kind"] = kind
    if "role" in payload or not partial:
        role = str(payload.get("role") or "").strip()
        if role not in SKILL_ROLES:
            raise HTTPException(status_code=422, detail=f"unknown role {role!r}")
        out["role"] = role
    if "tags" in payload or not partial:
        out["tags"] = _normalize_tags(payload.get("tags"))
    if "body" in payload or "body_md" in payload or not partial:
        body = str(payload.get("body") or payload.get("body_md") or "").strip()
        if not body:
            raise HTTPException(status_code=422, detail="body is required")
        out["body"] = body
    if "platform" in payload or not partial:
        out["platform"] = str(payload.get("platform") or "").strip()
    if "match" in payload or not partial:
        out["match"] = _normalize_match(payload.get("match"))
    if "inputs" in payload or not partial:
        out["inputs"] = _normalize_str_list(payload.get("inputs"))
    if "outputs" in payload or not partial:
        out["outputs"] = _normalize_str_list(payload.get("outputs"))
    if "reproducible" in payload or not partial:
        out["reproducible"] = bool(payload.get("reproducible", True))
    if "origin" in payload:
        origin = str(payload.get("origin") or "mutation")
        if origin not in SKILL_ORIGINS:
            raise HTTPException(status_code=422, detail=f"unknown origin {origin!r}")
        out["origin"] = origin
    if "origin_ref" in payload or not partial:
        out["origin_ref"] = str(payload.get("origin_ref") or "").strip()
    if "parent_skill_id" in payload:
        out["parent_skill_id"] = payload.get("parent_skill_id") or None
    return out


class SkillStore:
    def __init__(self, db: Any) -> None:
        self.db = db
        ensure_skill_schema(self.db.conn)
        self.db.conn.commit()

    def get(self, skill_id: str) -> dict[str, Any] | None:
        cur = self.db.conn.execute("SELECT * FROM skills WHERE id = ?", (skill_id,))
        row = cur.fetchone()
        return row_to_skill(row) if row else None

    def get_shared_by_slug(self, slug: str) -> dict[str, Any] | None:
        cur = self.db.conn.execute(
            "SELECT * FROM skills WHERE scope = 'shared' AND slug = ?",
            (slug,),
        )
        row = cur.fetchone()
        return row_to_skill(row) if row else None

    def get_local_by_slug(self, owner_user_id: str, slug: str) -> dict[str, Any] | None:
        cur = self.db.conn.execute(
            "SELECT * FROM skills WHERE scope = 'local' AND owner_user_id = ? AND slug = ?",
            (owner_user_id, slug),
        )
        row = cur.fetchone()
        return row_to_skill(row) if row else None

    def list_visible(
        self,
        principal: Principal,
        *,
        tag: str | None = None,
        role: str | None = None,
        platform: str | None = None,
        ats: str | None = None,
        url: str | None = None,
        scope: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        who = owner_key(principal)
        limit = max(1, min(int(limit), 500))
        if is_admin(principal):
            cur = self.db.conn.execute(
                "SELECT * FROM skills ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
        elif is_maintainer(principal):
            cur = self.db.conn.execute(
                """
                SELECT * FROM skills
                WHERE scope = 'shared' OR owner_user_id = ?
                ORDER BY updated_at DESC LIMIT ?
                """,
                (who, limit),
            )
        else:
            cur = self.db.conn.execute(
                """
                SELECT * FROM skills
                WHERE (scope = 'shared' AND status = 'approved')
                   OR (scope = 'local' AND owner_user_id = ?)
                ORDER BY updated_at DESC LIMIT ?
                """,
                (who, limit),
            )
        out: list[dict[str, Any]] = []
        for row in cur.fetchall():
            skill = row_to_skill(row)
            if not can_see_skill(principal, skill):
                continue
            if skill.get("status") == "retired" and not is_maintainer(principal):
                continue
            if skill_matches_query(
                skill,
                tag=tag,
                role=role,
                platform=platform,
                ats=ats,
                url=url,
                scope=scope,
                status=status,
            ):
                out.append(skill)
        return out

    def insert(self, fields: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        now = utc_now()
        skill_id = fields.get("id") or new_id("skl_")
        tags = list(fields.get("tags") or [])
        body = fields.get("body") or ""
        slug = fields["slug"]
        role = fields["role"]
        digest = fields.get("content_hash") or content_hash_for(body, slug, role, tags)
        self.db.conn.execute(
            """
            INSERT INTO skills (
                id, slug, name, kind, role, tags_json, scope, owner_user_id, status,
                platform, match_json, inputs_json, outputs_json, body_md, origin,
                origin_ref, parent_skill_id, version, content_hash, reproducible,
                proctor_status, proctor_note, proctor_evidence_json, approved_at,
                approved_by, created_at, updated_at, created_by
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?
            )
            """,
            (
                skill_id,
                slug,
                fields["name"],
                fields.get("kind") or "skill",
                role,
                _dump(tags),
                fields.get("scope") or "shared",
                fields.get("owner_user_id"),
                fields.get("status") or "draft",
                fields.get("platform") or "",
                _dump(fields.get("match") or {"ats": [], "url_patterns": [], "apply_kind": []}),
                _dump(fields.get("inputs") or []),
                _dump(fields.get("outputs") or []),
                body,
                fields.get("origin") or "mutation",
                fields.get("origin_ref") or "",
                fields.get("parent_skill_id"),
                int(fields.get("version") or 1),
                digest,
                1 if fields.get("reproducible", True) else 0,
                fields.get("proctor_status") or "none",
                fields.get("proctor_note") or "",
                _dump(fields.get("proctor_evidence") or {}),
                fields.get("approved_at"),
                fields.get("approved_by"),
                fields.get("created_at") or now,
                fields.get("updated_at") or now,
                fields.get("created_by") or "",
            ),
        )
        if commit:
            self.db.conn.commit()
        stored = self.get(skill_id)
        if stored is None:
            raise RuntimeError("skill insert did not persist")
        return stored

    def update(self, skill_id: str, fields: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        current = self.get(skill_id)
        if current is None:
            raise HTTPException(status_code=404, detail="skill not found")
        merged = dict(current)
        merged.update(fields)
        tags = list(merged.get("tags") or [])
        merged["content_hash"] = content_hash_for(
            merged.get("body") or "",
            merged["slug"],
            merged["role"],
            tags,
        )
        now = utc_now()
        self.db.conn.execute(
            """
            UPDATE skills SET
                slug = ?, name = ?, kind = ?, role = ?, tags_json = ?, scope = ?,
                owner_user_id = ?, status = ?, platform = ?, match_json = ?,
                inputs_json = ?, outputs_json = ?, body_md = ?, origin = ?,
                origin_ref = ?, parent_skill_id = ?, version = ?, content_hash = ?,
                reproducible = ?, proctor_status = ?, proctor_note = ?,
                proctor_evidence_json = ?, approved_at = ?, approved_by = ?,
                updated_at = ?, created_by = ?
            WHERE id = ?
            """,
            (
                merged["slug"],
                merged["name"],
                merged["kind"],
                merged["role"],
                _dump(tags),
                merged["scope"],
                merged.get("owner_user_id"),
                merged["status"],
                merged.get("platform") or "",
                _dump(merged.get("match") or {}),
                _dump(merged.get("inputs") or []),
                _dump(merged.get("outputs") or []),
                merged.get("body") or "",
                merged["origin"],
                merged.get("origin_ref") or "",
                merged.get("parent_skill_id"),
                int(merged.get("version") or 1),
                merged["content_hash"],
                1 if merged.get("reproducible", True) else 0,
                merged.get("proctor_status") or "none",
                merged.get("proctor_note") or "",
                _dump(merged.get("proctor_evidence") or {}),
                merged.get("approved_at"),
                merged.get("approved_by"),
                now,
                merged.get("created_by") or "",
                skill_id,
            ),
        )
        if commit:
            self.db.conn.commit()
        stored = self.get(skill_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="skill not found")
        return stored

    def upsert_github(self, fields: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """Seed or refresh a shared GitHub starter. Never overwrite promoted non-github rows."""
        slug = fields["slug"]
        existing = self.get_shared_by_slug(slug)
        now = utc_now()
        tags = list(fields.get("tags") or [])
        body = fields.get("body") or ""
        digest = content_hash_for(body, slug, fields["role"], tags)
        payload = {
            **fields,
            "scope": "shared",
            "owner_user_id": None,
            "status": "approved",
            "origin": "github",
            "content_hash": digest,
            "proctor_status": "passed",
            "approved_at": now,
            "approved_by": "github",
            "created_by": fields.get("created_by") or "github",
        }
        if existing is None:
            stored = self.insert(payload)
            return stored, "inserted"
        if existing.get("origin") != "github":
            return existing, "skipped"
        if existing.get("content_hash") == digest:
            return existing, "unchanged"
        updated = self.update(
            existing["id"],
            {
                "name": payload["name"],
                "kind": payload.get("kind") or "skill",
                "role": payload["role"],
                "tags": tags,
                "platform": payload.get("platform") or "",
                "match": payload.get("match"),
                "inputs": payload.get("inputs") or [],
                "outputs": payload.get("outputs") or [],
                "body": body,
                "origin_ref": payload.get("origin_ref") or "",
                "reproducible": payload.get("reproducible", True),
                "version": int(existing.get("version") or 1) + 1,
                "status": "approved",
                "proctor_status": "passed",
                "approved_at": existing.get("approved_at") or now,
                "approved_by": existing.get("approved_by") or "github",
            },
        )
        return updated, "updated"

    def get_recording(self, recording_id: str) -> dict[str, Any] | None:
        cur = self.db.conn.execute("SELECT * FROM skill_recordings WHERE id = ?", (recording_id,))
        row = cur.fetchone()
        return row_to_recording(row) if row else None

    def list_recordings(
        self,
        *,
        submitted_by: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        args: list[Any] = []
        if submitted_by:
            clauses.append("submitted_by = ?")
            args.append(submitted_by)
        if status:
            clauses.append("status = ?")
            args.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = max(1, min(int(limit), 500))
        cur = self.db.conn.execute(
            f"SELECT * FROM skill_recordings {where} ORDER BY created_at DESC LIMIT ?",
            [*args, limit],
        )
        return [row_to_recording(r) for r in cur.fetchall()]

    def insert_recording(
        self,
        *,
        skill_id: str | None,
        submitted_by: str,
        payload: dict[str, Any],
        queue_item_id: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        recording_id = new_id("rec_")
        self.db.conn.execute(
            """
            INSERT INTO skill_recordings (
                id, skill_id, submitted_by, payload_json, status, queue_item_id,
                proctor_note, proctor_evidence_json, reviewed_by, reviewed_at, created_at
            ) VALUES (?, ?, ?, ?, 'queued', ?, '', '{}', NULL, NULL, ?)
            """,
            (
                recording_id,
                skill_id,
                submitted_by,
                json.dumps(payload, ensure_ascii=False),
                queue_item_id,
                now,
            ),
        )
        self.db.conn.commit()
        stored = self.get_recording(recording_id)
        if stored is None:
            raise RuntimeError("recording insert did not persist")
        return stored

    def update_recording(self, recording_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        current = self.get_recording(recording_id)
        if current is None:
            raise HTTPException(status_code=404, detail="recording not found")
        assignments: list[str] = []
        values: list[Any] = []
        mapping = {
            "skill_id": "skill_id",
            "status": "status",
            "queue_item_id": "queue_item_id",
            "proctor_note": "proctor_note",
            "reviewed_by": "reviewed_by",
            "reviewed_at": "reviewed_at",
        }
        for key, col in mapping.items():
            if key in fields:
                assignments.append(f"{col} = ?")
                values.append(fields[key])
        if "payload" in fields:
            assignments.append("payload_json = ?")
            values.append(json.dumps(fields["payload"], ensure_ascii=False))
        if "proctor_evidence" in fields:
            assignments.append("proctor_evidence_json = ?")
            values.append(json.dumps(fields["proctor_evidence"] or {}, ensure_ascii=False))
        if not assignments:
            return current
        values.append(recording_id)
        self.db.conn.execute(
            f"UPDATE skill_recordings SET {', '.join(assignments)} WHERE id = ?",
            values,
        )
        self.db.conn.commit()
        stored = self.get_recording(recording_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="recording not found")
        return stored
