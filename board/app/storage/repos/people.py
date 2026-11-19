"""People SQL. HTTP stays in app.people; this module only reads and writes rows."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.tenant import TenantContext

SEARCH_MAX_CHARS = 48
LIST_DEFAULT_LIMIT = 200
_LIKE_ESCAPE = "!"

_COLUMNS = (
    "account_id",
    "id",
    "name",
    "title",
    "company",
    "job_id",
    "linkedin_url",
    "email",
    "email_confidence",
    "do_not_contact",
    "touches_json",
    "notes",
    "created_at",
    "updated_at",
)
_COLUMN_SQL = ", ".join(_COLUMNS)
_SEARCH_SQL = (
    "(name LIKE ? ESCAPE '!' OR company LIKE ? ESCAPE '!' OR title LIKE ? ESCAPE '!')"
)

PEOPLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    account_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    title TEXT,
    company TEXT,
    job_id TEXT,
    linkedin_url TEXT,
    email TEXT,
    email_confidence TEXT,
    do_not_contact INTEGER NOT NULL DEFAULT 0,
    touches_json TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account_id, id)
);

CREATE INDEX IF NOT EXISTS idx_people_job ON people(account_id, job_id);
CREATE INDEX IF NOT EXISTS idx_people_company ON people(account_id, company);
"""


def ensure_people_schema(conn: Any) -> None:
    conn.executescript(PEOPLE_SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def escape_like(value: str) -> str:
    """Escape ``%``, ``_``, and the escape character so LIKE matches them literally."""
    esc = _LIKE_ESCAPE
    return value.replace(esc, esc + esc).replace("%", esc + "%").replace("_", esc + "_")


def capped_search(q: str | None) -> str | None:
    if q is None:
        return None
    text = q.strip()
    if not text:
        return None
    return text[:SEARCH_MAX_CHARS]


def _normalize_limit(limit: int | None) -> int | None:
    """``None`` means no LIMIT. A non-positive value falls back to the list default."""
    if limit is None:
        return None
    value = int(limit)
    if value < 1:
        return LIST_DEFAULT_LIMIT
    return value


def row_to_person(row: Any) -> dict[str, Any]:
    data = dict(row)
    touches = json.loads(data["touches_json"] or "[]")
    return {
        "id": data["id"],
        "name": data["name"],
        "title": data["title"] or "",
        "company": data["company"] or "",
        "job_id": data["job_id"] or None,
        "linkedin_url": data["linkedin_url"] or "",
        "email": data["email"] or "",
        "email_confidence": data["email_confidence"] or "",
        "do_not_contact": bool(data["do_not_contact"]),
        "touches": touches if isinstance(touches, list) else [],
        "notes": data["notes"] or "",
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }


class PeopleRepo:
    """Tenant-scoped people rows. ``db`` is a BoardDB-like object with ``.conn``."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def get(self, tenant: TenantContext, person_id: str) -> dict[str, Any] | None:
        cur = self._db.conn.execute(
            f"SELECT {_COLUMN_SQL} FROM people WHERE account_id = ? AND id = ?",
            (tenant.account_id, person_id),
        )
        row = cur.fetchone()
        return row_to_person(row) if row else None

    def list(
        self,
        tenant: TenantContext,
        *,
        job_id: str | None = None,
        q: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["account_id = ?"]
        args: list[Any] = [tenant.account_id]
        if job_id:
            clauses.append("job_id = ?")
            args.append(job_id)
        needle = capped_search(q)
        if needle is not None:
            like = f"%{escape_like(needle)}%"
            clauses.append(_SEARCH_SQL)
            args.extend([like, like, like])
        sql = (
            f"SELECT {_COLUMN_SQL} FROM people WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC"
        )
        bounded = _normalize_limit(limit)
        if bounded is not None:
            sql += " LIMIT ?"
            args.append(bounded)
        cur = self._db.conn.execute(sql, args)
        return [row_to_person(row) for row in cur.fetchall()]

    def insert(self, tenant: TenantContext, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        self._db.conn.execute(
            """
            INSERT INTO people (
                account_id, id, name, title, company, job_id, linkedin_url, email, email_confidence,
                do_not_contact, touches_json, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant.account_id,
                payload["id"],
                payload["name"],
                payload.get("title") or "",
                payload.get("company") or "",
                payload.get("job_id") or None,
                payload.get("linkedin_url") or "",
                payload.get("email") or "",
                payload.get("email_confidence") or "",
                1 if payload.get("do_not_contact") else 0,
                json.dumps(payload.get("touches") or [], ensure_ascii=False),
                payload.get("notes") or "",
                payload.get("created_at") or now,
                payload.get("updated_at") or now,
            ),
        )
        self._db.conn.commit()
        stored = self.get(tenant, payload["id"])
        assert stored is not None
        return stored

    def update(
        self, tenant: TenantContext, person_id: str, patch: dict[str, Any]
    ) -> dict[str, Any] | None:
        current = self.get(tenant, person_id)
        if current is None:
            return None
        merged = {**current, **patch}
        self._db.conn.execute(
            """
            UPDATE people SET
                name=?, title=?, company=?, job_id=?, linkedin_url=?, email=?,
                email_confidence=?, do_not_contact=?, touches_json=?, notes=?, updated_at=?
            WHERE account_id=? AND id=?
            """,
            (
                merged["name"],
                merged.get("title") or "",
                merged.get("company") or "",
                merged.get("job_id") or None,
                merged.get("linkedin_url") or "",
                merged.get("email") or "",
                merged.get("email_confidence") or "",
                1 if merged.get("do_not_contact") else 0,
                json.dumps(merged.get("touches") or [], ensure_ascii=False),
                merged.get("notes") or "",
                _now(),
                tenant.account_id,
                person_id,
            ),
        )
        self._db.conn.commit()
        stored = self.get(tenant, person_id)
        assert stored is not None
        return stored
