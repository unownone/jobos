"""Skill registry: shared GitHub starters + per-bot local forks + memory solidify."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from typing import Any, Sequence
from urllib.parse import urlparse

from fastapi import HTTPException

from app.auth import Principal
from app.bootstrap import new_id
from app.db import utc_now
from app.storage.repos.registry import SkillRepo, apply_skill_schema
from app.tenant import COMPAT_ACCOUNT_ID, TenantContext
from app.tenant_schema import ensure_tenant_schema

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")

SKILL_ROLES = ("discovery", "apply", "outreach", "research", "maintain")
SKILL_KINDS = ("skill", "mcp", "http", "builtin")
SKILL_SCOPES = ("shared", "local")
SKILL_STATUSES = ("draft", "recorded", "proctoring", "approved", "rejected", "retired")
SKILL_ORIGINS = ("github", "recording", "mutation", "memory")
PROCTOR_STATUSES = ("none", "pending", "passed", "failed")
RECORDING_STATUSES = ("queued", "proctoring", "passed", "failed", "promoted", "declined")
MOTION_TAGS = ("source", "apply", "outreach", "research", "maintain")

def ensure_skill_schema(conn: Any) -> None:
    apply_skill_schema(conn)
    ensure_tenant_schema(conn)


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
        "body": (data.get("body_md") or "") if "body_md" in data else "",
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
    def __init__(self, db: Any, tenant: TenantContext | None = None) -> None:
        self.db = db
        self.tenant = tenant or TenantContext(COMPAT_ACCOUNT_ID)
        ensure_skill_schema(self.db.conn)
        self.db.conn.commit()
        self.repo = SkillRepo(self.db.conn)

    @property
    def account_id(self) -> str:
        return self.tenant.account_id

    def for_tenant(self, tenant: TenantContext) -> SkillStore:
        return SkillStore(self.db, tenant)

    def get(self, skill_id: str) -> dict[str, Any] | None:
        row = self.repo.get_skill(self.account_id, skill_id)
        return row_to_skill(row) if row else None

    def get_shared_by_slug(self, slug: str) -> dict[str, Any] | None:
        row = self.repo.get_shared_by_slug(self.account_id, slug)
        return row_to_skill(row) if row else None

    def get_local_by_slug(self, owner_user_id: str, slug: str) -> dict[str, Any] | None:
        row = self.repo.get_local_by_slug(self.account_id, owner_user_id, slug)
        return row_to_skill(row) if row else None

    def skill_bodies(self, skill_ids: Sequence[str]) -> dict[str, str]:
        """Markdown for ids the caller already decided to return."""
        return self.repo.skill_bodies(self.account_id, skill_ids)

    def list_approved_shared(
        self,
        *,
        tag: str | None = None,
        role: str | None = None,
        platform: str | None = None,
        ats: str | None = None,
        url: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Approved shared catalog only. Summary rows: no markdown body."""
        limit = max(1, min(int(limit), 500))
        rows = self.repo.list_approved_shared_summary(self.account_id, limit)
        out: list[dict[str, Any]] = []
        for row in rows:
            skill = row_to_skill(row)
            if skill_matches_query(
                skill,
                tag=tag,
                role=role,
                platform=platform,
                ats=ats,
                url=url,
                scope="shared",
                status="approved",
            ):
                out.append(skill)
        return out

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
            rows = self.repo.list_admin_summary(self.account_id, limit)
        elif is_maintainer(principal):
            rows = self.repo.list_maintainer_summary(self.account_id, who, limit)
        else:
            rows = self.repo.list_member_summary(self.account_id, who, limit)
        out: list[dict[str, Any]] = []
        for row in rows:
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
        self.repo.insert_skill(
            self.account_id,
            {
                "id": skill_id,
                "slug": slug,
                "name": fields["name"],
                "kind": fields.get("kind") or "skill",
                "role": role,
                "tags": tags,
                "scope": fields.get("scope") or "shared",
                "owner_user_id": fields.get("owner_user_id"),
                "status": fields.get("status") or "draft",
                "platform": fields.get("platform") or "",
                "match": fields.get("match") or {"ats": [], "url_patterns": [], "apply_kind": []},
                "inputs": fields.get("inputs") or [],
                "outputs": fields.get("outputs") or [],
                "body": body,
                "origin": fields.get("origin") or "mutation",
                "origin_ref": fields.get("origin_ref") or "",
                "parent_skill_id": fields.get("parent_skill_id"),
                "version": int(fields.get("version") or 1),
                "content_hash": digest,
                "reproducible": bool(fields.get("reproducible", True)),
                "proctor_status": fields.get("proctor_status") or "none",
                "proctor_note": fields.get("proctor_note") or "",
                "proctor_evidence": fields.get("proctor_evidence") or {},
                "approved_at": fields.get("approved_at"),
                "approved_by": fields.get("approved_by"),
                "created_at": fields.get("created_at") or now,
                "updated_at": fields.get("updated_at") or now,
                "created_by": fields.get("created_by") or "",
            },
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
        self.repo.update_skill(self.account_id, skill_id, merged, updated_at=now)
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
            payload["id"] = fields.get("id") or f"skl_{slug}"
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
        row = self.repo.get_recording(self.account_id, recording_id)
        return row_to_recording(row) if row else None

    def list_recordings(
        self,
        *,
        submitted_by: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        rows = self.repo.list_recordings(
            self.account_id,
            submitted_by=submitted_by,
            status=status,
            limit=limit,
        )
        return [row_to_recording(row) for row in rows]

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
        self.repo.insert_recording(
            recording_id=recording_id,
            account_id=self.account_id,
            skill_id=skill_id,
            submitted_by=submitted_by,
            payload=payload,
            queue_item_id=queue_item_id,
            created_at=now,
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
        if not self.repo.update_recording(self.account_id, recording_id, fields):
            return current
        self.db.conn.commit()
        stored = self.get_recording(recording_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="recording not found")
        return stored
