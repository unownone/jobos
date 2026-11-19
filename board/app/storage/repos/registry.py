"""Skill, recording, and MCP SQL.

List queries name their columns and omit ``body_md``. Point reads include it.
Tag and URL filters stay in Python; this module only applies the indexed
predicates (account, scope, status, owner) and a LIMIT.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from app.storage.dialect import chunked_in, sqlite_dialect

# Repo SQL uses ``?``. SqlConnection rewrites that for Postgres. sqlite_dialect
# is the placeholder and the 100-parameter budget, not a claim about the engine.
_DIALECT = sqlite_dialect()
_IN_CHUNK_RESERVED = 8

SKILL_SUMMARY_COLUMNS: tuple[str, ...] = (
    "id",
    "slug",
    "name",
    "kind",
    "role",
    "tags_json",
    "scope",
    "owner_user_id",
    "status",
    "platform",
    "match_json",
    "inputs_json",
    "outputs_json",
    "origin",
    "origin_ref",
    "parent_skill_id",
    "version",
    "content_hash",
    "reproducible",
    "proctor_status",
    "proctor_note",
    "proctor_evidence_json",
    "approved_at",
    "approved_by",
    "created_at",
    "updated_at",
    "created_by",
)
SKILL_FULL_COLUMNS: tuple[str, ...] = SKILL_SUMMARY_COLUMNS + ("body_md",)

RECORDING_COLUMNS: tuple[str, ...] = (
    "id",
    "skill_id",
    "submitted_by",
    "payload_json",
    "status",
    "queue_item_id",
    "proctor_note",
    "proctor_evidence_json",
    "reviewed_by",
    "reviewed_at",
    "created_at",
)

MCP_COLUMNS: tuple[str, ...] = (
    "id",
    "slug",
    "name",
    "kind",
    "status",
    "verdict",
    "capability_json",
    "roles_json",
    "platforms_json",
    "source",
    "install",
    "auth",
    "notes",
    "reason",
    "next_action",
    "config_json",
    "hosted",
    "origin",
    "origin_ref",
    "version",
    "content_hash",
    "created_at",
    "updated_at",
)

_SKILL_SUMMARY_SQL = ", ".join(SKILL_SUMMARY_COLUMNS)
_SKILL_FULL_SQL = ", ".join(SKILL_FULL_COLUMNS)
_RECORDING_SQL = ", ".join(RECORDING_COLUMNS)
_MCP_SQL = ", ".join(MCP_COLUMNS)

_RECORDING_ASSIGNMENTS = {
    "skill_id": "skill_id",
    "status": "status",
    "queue_item_id": "queue_item_id",
    "proctor_note": "proctor_note",
    "reviewed_by": "reviewed_by",
    "reviewed_at": "reviewed_at",
}

SKILL_SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    account_id TEXT NOT NULL,
    id TEXT NOT NULL,
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
    created_by TEXT,
    PRIMARY KEY (account_id, id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_account_shared_slug
    ON skills(account_id, slug) WHERE scope = 'shared';

CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_account_local_slug
    ON skills(account_id, owner_user_id, slug) WHERE scope = 'local';

CREATE INDEX IF NOT EXISTS idx_skills_role_status ON skills(role, status);
CREATE INDEX IF NOT EXISTS idx_skills_owner ON skills(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_skills_origin ON skills(origin);
CREATE INDEX IF NOT EXISTS idx_skills_account_updated ON skills(account_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_skills_account_scope_status ON skills(account_id, scope, status);

CREATE TABLE IF NOT EXISTS skill_recordings (
    account_id TEXT NOT NULL,
    id TEXT NOT NULL,
    skill_id TEXT,
    submitted_by TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    queue_item_id TEXT,
    proctor_note TEXT,
    proctor_evidence_json TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (account_id, id)
);

CREATE INDEX IF NOT EXISTS idx_skill_recordings_status ON skill_recordings(account_id, status);
CREATE INDEX IF NOT EXISTS idx_skill_recordings_submitter ON skill_recordings(account_id, submitted_by);
CREATE INDEX IF NOT EXISTS idx_skill_recordings_account_created
    ON skill_recordings(account_id, created_at);
"""

MCP_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcps (
    account_id TEXT NOT NULL,
    id TEXT NOT NULL,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'mcp',
    status TEXT NOT NULL DEFAULT 'adopted',
    verdict TEXT,
    capability_json TEXT NOT NULL DEFAULT '[]',
    roles_json TEXT NOT NULL DEFAULT '[]',
    platforms_json TEXT NOT NULL DEFAULT '[]',
    source TEXT,
    install TEXT,
    auth TEXT,
    notes TEXT,
    reason TEXT,
    next_action TEXT,
    config_json TEXT,
    hosted TEXT,
    origin TEXT NOT NULL DEFAULT 'github',
    origin_ref TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account_id, id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mcps_account_slug ON mcps(account_id, slug);
CREATE INDEX IF NOT EXISTS idx_mcps_status ON mcps(status);
CREATE INDEX IF NOT EXISTS idx_mcps_kind ON mcps(kind);
CREATE INDEX IF NOT EXISTS idx_mcps_origin ON mcps(origin);
CREATE INDEX IF NOT EXISTS idx_mcps_account_status_slug ON mcps(account_id, status, slug);
"""


def apply_skill_schema(conn: Any) -> None:
    conn.executescript(SKILL_SCHEMA)


def apply_mcp_schema(conn: Any) -> None:
    conn.executescript(MCP_SCHEMA)


def _dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _bit(value: Any) -> int:
    return 1 if value else 0


def _rows(cursor: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def _row(cursor: Any) -> dict[str, Any] | None:
    found = cursor.fetchone()
    if found is None:
        return None
    return dict(found)


def _ids(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("ids must be a sequence of strings")
    return tuple(str(item) for item in values if item)


class SkillRepo:
    """Skills and skill recordings. List methods never select ``body_md``."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def get_skill(self, account_id: str, skill_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute(
            f"SELECT {_SKILL_FULL_SQL} FROM skills WHERE id = ? AND account_id = ?",
            (skill_id, account_id),
        )
        return _row(cur)

    def get_shared_by_slug(self, account_id: str, slug: str) -> dict[str, Any] | None:
        cur = self.conn.execute(
            f"""
            SELECT {_SKILL_FULL_SQL} FROM skills
            WHERE account_id = ? AND scope = 'shared' AND slug = ?
            """,
            (account_id, slug),
        )
        return _row(cur)

    def get_local_by_slug(
        self, account_id: str, owner_user_id: str, slug: str
    ) -> dict[str, Any] | None:
        cur = self.conn.execute(
            f"""
            SELECT {_SKILL_FULL_SQL} FROM skills
            WHERE account_id = ? AND scope = 'local' AND owner_user_id = ? AND slug = ?
            """,
            (account_id, owner_user_id, slug),
        )
        return _row(cur)

    def list_approved_shared_summary(self, account_id: str, limit: int) -> list[dict[str, Any]]:
        """Approved shared catalog page. No markdown body."""
        return self._list_summary(
            "account_id = ? AND scope = 'shared' AND status = 'approved'",
            (account_id,),
            limit,
        )

    def list_admin_summary(self, account_id: str, limit: int) -> list[dict[str, Any]]:
        return self._list_summary("account_id = ?", (account_id,), limit)

    def list_maintainer_summary(
        self, account_id: str, owner_user_id: str, limit: int
    ) -> list[dict[str, Any]]:
        return self._list_summary(
            "account_id = ? AND (scope = 'shared' OR owner_user_id = ?)",
            (account_id, owner_user_id),
            limit,
        )

    def list_member_summary(
        self, account_id: str, owner_user_id: str, limit: int
    ) -> list[dict[str, Any]]:
        return self._list_summary(
            """
            account_id = ?
              AND (
                (scope = 'shared' AND status = 'approved')
                OR (scope = 'local' AND owner_user_id = ?)
              )
            """,
            (account_id, owner_user_id),
            limit,
        )

    def skill_bodies(self, account_id: str, skill_ids: Sequence[str]) -> dict[str, str]:
        """Load markdown for an already-filtered id list. Not a list projection."""
        found: dict[str, str] = {}
        ids = _ids(skill_ids)
        for clause, params in chunked_in(_DIALECT, "id", ids, reserved=_IN_CHUNK_RESERVED):
            cur = self.conn.execute(
                f"SELECT id, body_md FROM skills WHERE account_id = ? AND {clause}",
                (account_id, *params),
            )
            for row in _rows(cur):
                found[str(row["id"])] = row["body_md"] or ""
        return found

    def insert_skill(self, account_id: str, fields: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO skills (
                id, account_id, slug, name, kind, role, tags_json, scope, owner_user_id, status,
                platform, match_json, inputs_json, outputs_json, body_md, origin,
                origin_ref, parent_skill_id, version, content_hash, reproducible,
                proctor_status, proctor_note, proctor_evidence_json, approved_at,
                approved_by, created_at, updated_at, created_by
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?
            )
            """,
            (
                fields["id"],
                account_id,
                fields["slug"],
                fields["name"],
                fields.get("kind") or "skill",
                fields["role"],
                _dump(list(fields.get("tags") or [])),
                fields.get("scope") or "shared",
                fields.get("owner_user_id"),
                fields.get("status") or "draft",
                fields.get("platform") or "",
                _dump(fields.get("match") or {"ats": [], "url_patterns": [], "apply_kind": []}),
                _dump(list(fields.get("inputs") or [])),
                _dump(list(fields.get("outputs") or [])),
                fields.get("body") or "",
                fields.get("origin") or "mutation",
                fields.get("origin_ref") or "",
                fields.get("parent_skill_id"),
                int(fields.get("version") or 1),
                fields["content_hash"],
                _bit(fields.get("reproducible", True)),
                fields.get("proctor_status") or "none",
                fields.get("proctor_note") or "",
                _dump(fields.get("proctor_evidence") or {}),
                fields.get("approved_at"),
                fields.get("approved_by"),
                fields["created_at"],
                fields["updated_at"],
                fields.get("created_by") or "",
            ),
        )

    def update_skill(
        self,
        account_id: str,
        skill_id: str,
        fields: dict[str, Any],
        *,
        updated_at: str,
    ) -> None:
        self.conn.execute(
            """
            UPDATE skills SET
                slug = ?, name = ?, kind = ?, role = ?, tags_json = ?, scope = ?,
                owner_user_id = ?, status = ?, platform = ?, match_json = ?,
                inputs_json = ?, outputs_json = ?, body_md = ?, origin = ?,
                origin_ref = ?, parent_skill_id = ?, version = ?, content_hash = ?,
                reproducible = ?, proctor_status = ?, proctor_note = ?,
                proctor_evidence_json = ?, approved_at = ?, approved_by = ?,
                updated_at = ?, created_by = ?
            WHERE id = ? AND account_id = ?
            """,
            (
                fields["slug"],
                fields["name"],
                fields["kind"],
                fields["role"],
                _dump(list(fields.get("tags") or [])),
                fields["scope"],
                fields.get("owner_user_id"),
                fields["status"],
                fields.get("platform") or "",
                _dump(fields.get("match") or {}),
                _dump(list(fields.get("inputs") or [])),
                _dump(list(fields.get("outputs") or [])),
                fields.get("body") or "",
                fields["origin"],
                fields.get("origin_ref") or "",
                fields.get("parent_skill_id"),
                int(fields.get("version") or 1),
                fields["content_hash"],
                _bit(fields.get("reproducible", True)),
                fields.get("proctor_status") or "none",
                fields.get("proctor_note") or "",
                _dump(fields.get("proctor_evidence") or {}),
                fields.get("approved_at"),
                fields.get("approved_by"),
                updated_at,
                fields.get("created_by") or "",
                skill_id,
                account_id,
            ),
        )

    def get_recording(self, account_id: str, recording_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute(
            f"SELECT {_RECORDING_SQL} FROM skill_recordings WHERE id = ? AND account_id = ?",
            (recording_id, account_id),
        )
        return _row(cur)

    def list_recordings(
        self,
        account_id: str,
        *,
        submitted_by: str | None,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        clauses = ["account_id = ?"]
        args: list[Any] = [account_id]
        if submitted_by:
            clauses.append("submitted_by = ?")
            args.append(submitted_by)
        if status:
            clauses.append("status = ?")
            args.append(status)
        where = " AND ".join(clauses)
        cur = self.conn.execute(
            f"""
            SELECT {_RECORDING_SQL} FROM skill_recordings
            WHERE {where}
            ORDER BY created_at DESC LIMIT ?
            """,
            (*args, limit),
        )
        return _rows(cur)

    def insert_recording(
        self,
        *,
        recording_id: str,
        account_id: str,
        skill_id: str | None,
        submitted_by: str,
        payload: dict[str, Any],
        queue_item_id: str | None,
        created_at: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO skill_recordings (
                id, account_id, skill_id, submitted_by, payload_json, status, queue_item_id,
                proctor_note, proctor_evidence_json, reviewed_by, reviewed_at, created_at
            ) VALUES (?, ?, ?, ?, ?, 'queued', ?, '', '{}', NULL, NULL, ?)
            """,
            (
                recording_id,
                account_id,
                skill_id,
                submitted_by,
                json.dumps(payload, ensure_ascii=False),
                queue_item_id,
                created_at,
            ),
        )

    def update_recording(self, account_id: str, recording_id: str, fields: dict[str, Any]) -> bool:
        assignments: list[str] = []
        values: list[Any] = []
        for key, column in _RECORDING_ASSIGNMENTS.items():
            if key in fields:
                assignments.append(f"{column} = ?")
                values.append(fields[key])
        if "payload" in fields:
            assignments.append("payload_json = ?")
            values.append(json.dumps(fields["payload"], ensure_ascii=False))
        if "proctor_evidence" in fields:
            assignments.append("proctor_evidence_json = ?")
            values.append(json.dumps(fields["proctor_evidence"] or {}, ensure_ascii=False))
        if not assignments:
            return False
        values.extend([recording_id, account_id])
        self.conn.execute(
            f"UPDATE skill_recordings SET {', '.join(assignments)} WHERE id = ? AND account_id = ?",
            values,
        )
        return True

    def _list_summary(
        self, where: str, params: tuple[Any, ...], limit: int
    ) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            f"""
            SELECT {_SKILL_SUMMARY_SQL} FROM skills
            WHERE {where}
            ORDER BY updated_at DESC LIMIT ?
            """,
            (*params, limit),
        )
        return _rows(cur)


class McpRepo:
    """MCP registry. Rows have no markdown body; list and get share one projection."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def get(self, account_id: str, mcp_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute(
            f"SELECT {_MCP_SQL} FROM mcps WHERE id = ? AND account_id = ?",
            (mcp_id, account_id),
        )
        return _row(cur)

    def get_by_slug(self, account_id: str, slug: str) -> dict[str, Any] | None:
        cur = self.conn.execute(
            f"SELECT {_MCP_SQL} FROM mcps WHERE account_id = ? AND slug = ?",
            (account_id, slug),
        )
        return _row(cur)

    def list_mcps(self, account_id: str, limit: int) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            f"""
            SELECT {_MCP_SQL} FROM mcps
            WHERE account_id = ?
            ORDER BY status, slug LIMIT ?
            """,
            (account_id, limit),
        )
        return _rows(cur)

    def insert_mcp(self, account_id: str, fields: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO mcps (
                id, account_id, slug, name, kind, status, verdict, capability_json, roles_json,
                platforms_json, source, install, auth, notes, reason, next_action,
                config_json, hosted, origin, origin_ref, version, content_hash,
                created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?
            )
            """,
            (
                fields["id"],
                account_id,
                fields["slug"],
                fields["name"],
                fields["kind"],
                fields["status"],
                fields.get("verdict") or "",
                _dump(list(fields.get("capability") or [])),
                _dump(list(fields.get("roles") or [])),
                _dump(list(fields.get("platforms") or [])),
                fields.get("source") or "",
                fields.get("install") or "",
                fields.get("auth") or "",
                fields.get("notes") or "",
                fields.get("reason") or "",
                fields.get("next_action") or "",
                _dump(fields.get("config") or {}),
                fields.get("hosted") or "",
                fields["origin"],
                fields.get("origin_ref") or "",
                int(fields.get("version") or 1),
                fields["content_hash"],
                fields["created_at"],
                fields["updated_at"],
            ),
        )

    def update_mcp(
        self,
        account_id: str,
        mcp_id: str,
        fields: dict[str, Any],
        *,
        updated_at: str,
    ) -> None:
        self.conn.execute(
            """
            UPDATE mcps SET
                slug = ?, name = ?, kind = ?, status = ?, verdict = ?,
                capability_json = ?, roles_json = ?, platforms_json = ?,
                source = ?, install = ?, auth = ?, notes = ?, reason = ?,
                next_action = ?, config_json = ?, hosted = ?, origin = ?,
                origin_ref = ?, version = ?, content_hash = ?, updated_at = ?
            WHERE id = ? AND account_id = ?
            """,
            (
                fields["slug"],
                fields["name"],
                fields["kind"],
                fields["status"],
                fields.get("verdict") or "",
                _dump(list(fields.get("capability") or [])),
                _dump(list(fields.get("roles") or [])),
                _dump(list(fields.get("platforms") or [])),
                fields.get("source") or "",
                fields.get("install") or "",
                fields.get("auth") or "",
                fields.get("notes") or "",
                fields.get("reason") or "",
                fields.get("next_action") or "",
                _dump(fields.get("config") or {}),
                fields.get("hosted") or "",
                fields["origin"],
                fields.get("origin_ref") or "",
                int(fields.get("version") or 1),
                fields["content_hash"],
                updated_at,
                mcp_id,
                account_id,
            ),
        )
