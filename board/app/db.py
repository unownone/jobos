"""SQLite store for jobs + append-only events."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.constants import JSON_FIELDS, STATUSES

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    remote TEXT,
    url TEXT,
    apply_url TEXT,
    apply_kind TEXT,
    ats TEXT,
    req_id TEXT,
    sources_json TEXT,
    status TEXT NOT NULL,
    score REAL,
    owners_json TEXT,
    apply_packet_json TEXT,
    outreach_packet_json TEXT,
    research_json TEXT,
    proof_json TEXT,
    notes TEXT,
    conflicts_json TEXT,
    stopped INTEGER NOT NULL DEFAULT 0,
    stop_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    created_by_role TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    job_id TEXT,
    actor_role TEXT NOT NULL,
    actor TEXT,
    action TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    note TEXT,
    fields_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_apply_url ON jobs(apply_url);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id);

CREATE TABLE IF NOT EXISTS secrets_meta (
    key TEXT PRIMARY KEY,
    value_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    used_at TEXT,
    extra_json TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    track TEXT,
    email TEXT,
    password_hash TEXT,
    display_name TEXT,
    metadata_json TEXT,
    created_by TEXT,
    disabled_at TEXT,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email
    ON users(email) WHERE email IS NOT NULL AND email != '';

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""

COLUMN_TO_FIELD = {
    "sources_json": "sources",
    "owners_json": "owners",
    "apply_packet_json": "apply_packet",
    "outreach_packet_json": "outreach_packet",
    "research_json": "research",
    "proof_json": "proof",
    "conflicts_json": "conflicts",
}

FIELD_TO_COLUMN = {v: k for k, v in COLUMN_TO_FIELD.items()}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _load(raw: str | None, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    return json.loads(raw)


def row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    job: dict[str, Any] = {
        "id": data["id"],
        "company": data["company"],
        "title": data["title"],
        "location": data["location"] or "",
        "remote": data["remote"],
        "url": data["url"] or "",
        "apply_url": data["apply_url"] or "",
        "apply_kind": data["apply_kind"] or "",
        "ats": data["ats"] or "",
        "req_id": data["req_id"] or "",
        "sources": _load(data["sources_json"], []),
        "status": data["status"],
        "score": data["score"],
        "owners": _load(data["owners_json"], {"discovery": "", "apply": "", "outreach": ""}),
        "apply_packet": _load(data["apply_packet_json"], {}),
        "outreach_packet": _load(data["outreach_packet_json"], {}),
        "research": _load(data["research_json"], {}),
        "proof": _load(data["proof_json"], {}),
        "notes": data["notes"] or "",
        "conflicts": _load(data["conflicts_json"], []),
        "stopped": bool(data["stopped"]),
        "stop_reason": data["stop_reason"] or "",
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "created_by_role": data["created_by_role"] or "",
    }
    return job


class BoardDB:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = connect(db_path)

    def close(self) -> None:
        self.conn.close()

    def list_jobs(
        self,
        *,
        status: str | None = None,
        q: str | None = None,
        stopped: bool | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        args: list[Any] = []
        if status:
            clauses.append("status = ?")
            args.append(status)
        if stopped is not None:
            clauses.append("stopped = ?")
            args.append(1 if stopped else 0)
        if q:
            like = f"%{q}%"
            clauses.append(
                "(id LIKE ? OR company LIKE ? OR title LIKE ? OR apply_url LIKE ? OR notes LIKE ?)"
            )
            args.extend([like, like, like, like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = self.conn.execute(
            f"SELECT * FROM jobs {where} ORDER BY updated_at DESC",
            args,
        )
        return [row_to_job(r) for r in cur.fetchall()]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cur.fetchone()
        return row_to_job(row) if row else None

    def find_duplicate(
        self,
        *,
        apply_url: str,
        company: str,
        title: str,
        location: str,
        exclude_id: str | None = None,
    ) -> dict[str, Any] | None:
        if apply_url:
            cur = self.conn.execute(
                "SELECT * FROM jobs WHERE apply_url = ? AND apply_url != ''",
                (apply_url,),
            )
            row = cur.fetchone()
            if row and row["id"] != exclude_id:
                return row_to_job(row)
        cur = self.conn.execute(
            """
            SELECT * FROM jobs
            WHERE lower(company) = lower(?) AND lower(title) = lower(?)
              AND lower(COALESCE(location, '')) = lower(?)
            """,
            (company, title, location or ""),
        )
        row = cur.fetchone()
        if row and row["id"] != exclude_id:
            return row_to_job(row)
        return None

    def insert_job(self, job: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO jobs (
                id, company, title, location, remote, url, apply_url, apply_kind, ats, req_id,
                sources_json, status, score, owners_json, apply_packet_json, outreach_packet_json,
                research_json, proof_json, notes, conflicts_json, stopped, stop_reason,
                created_at, updated_at, created_by_role
            ) VALUES (
                :id, :company, :title, :location, :remote, :url, :apply_url, :apply_kind, :ats, :req_id,
                :sources_json, :status, :score, :owners_json, :apply_packet_json, :outreach_packet_json,
                :research_json, :proof_json, :notes, :conflicts_json, :stopped, :stop_reason,
                :created_at, :updated_at, :created_by_role
            )
            """,
            {
                "id": job["id"],
                "company": job["company"],
                "title": job["title"],
                "location": job.get("location") or "",
                "remote": _remote_to_text(job.get("remote")),
                "url": job.get("url") or "",
                "apply_url": job.get("apply_url") or "",
                "apply_kind": job.get("apply_kind") or "",
                "ats": job.get("ats") or "",
                "req_id": job.get("req_id") or "",
                "sources_json": _dump(job.get("sources") or []),
                "status": job.get("status") or "discovered",
                "score": job.get("score"),
                "owners_json": _dump(_owners(job.get("owners"))),
                "apply_packet_json": _dump(job.get("apply_packet") or {}),
                "outreach_packet_json": _dump(job.get("outreach_packet") or {}),
                "research_json": _dump(job.get("research") or {}),
                "proof_json": _dump(job.get("proof") or {}),
                "notes": job.get("notes") or "",
                "conflicts_json": _dump(job.get("conflicts") or []),
                "stopped": 1 if job.get("stopped") else 0,
                "stop_reason": job.get("stop_reason") or "",
                "created_at": job.get("created_at") or now,
                "updated_at": job.get("updated_at") or now,
                "created_by_role": job.get("created_by_role") or "",
            },
        )
        self.conn.commit()
        stored = self.get_job(job["id"])
        if stored is None:
            raise RuntimeError("insert did not persist")
        return stored

    def update_job(self, job_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        if not fields:
            stored = self.get_job(job_id)
            if stored is None:
                raise KeyError(job_id)
            return stored
        assignments: list[str] = []
        values: dict[str, Any] = {"id": job_id, "updated_at": utc_now()}
        for key, value in fields.items():
            if key in JSON_FIELDS:
                col = FIELD_TO_COLUMN[key]
                assignments.append(f"{col} = :{col}")
                values[col] = _dump(value)
            elif key == "remote":
                assignments.append("remote = :remote")
                values["remote"] = _remote_to_text(value)
            elif key == "stopped":
                assignments.append("stopped = :stopped")
                values["stopped"] = 1 if value else 0
            elif key in {
                "company",
                "title",
                "location",
                "url",
                "apply_url",
                "apply_kind",
                "ats",
                "req_id",
                "status",
                "score",
                "notes",
                "stop_reason",
            }:
                assignments.append(f"{key} = :{key}")
                values[key] = value
        assignments.append("updated_at = :updated_at")
        self.conn.execute(
            f"UPDATE jobs SET {', '.join(assignments)} WHERE id = :id",
            values,
        )
        self.conn.commit()
        stored = self.get_job(job_id)
        if stored is None:
            raise KeyError(job_id)
        return stored

    def delete_job(self, job_id: str) -> None:
        self.conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        self.conn.commit()

    def add_event(
        self,
        *,
        job_id: str | None,
        actor_role: str,
        actor: str | None,
        action: str,
        from_status: str | None = None,
        to_status: str | None = None,
        note: str | None = None,
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ts = utc_now()
        cur = self.conn.execute(
            """
            INSERT INTO events (
                ts, job_id, actor_role, actor, action, from_status, to_status, note, fields_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts,
                job_id,
                actor_role,
                actor or "",
                action,
                from_status,
                to_status,
                note or "",
                _dump(fields) if fields else None,
            ),
        )
        self.conn.commit()
        return {
            "id": cur.lastrowid,
            "ts": ts,
            "job_id": job_id,
            "actor_role": actor_role,
            "actor": actor or "",
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "note": note or "",
            "fields": fields or {},
        }

    def list_events(self, *, job_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        if job_id:
            cur = self.conn.execute(
                "SELECT * FROM events WHERE job_id = ? ORDER BY id DESC LIMIT ?",
                (job_id, limit),
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        out: list[dict[str, Any]] = []
        for row in cur.fetchall():
            out.append(
                {
                    "id": row["id"],
                    "ts": row["ts"],
                    "job_id": row["job_id"],
                    "actor_role": row["actor_role"],
                    "actor": row["actor"] or "",
                    "action": row["action"],
                    "from_status": row["from_status"],
                    "to_status": row["to_status"],
                    "note": row["note"] or "",
                    "fields": _load(row["fields_json"], {}),
                }
            )
        return out

    def counts_by_status(self) -> dict[str, int]:
        cur = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
        )
        found = {row["status"]: row["n"] for row in cur.fetchall()}
        return {status: int(found.get(status, 0)) for status in STATUSES}

    def vacuum(self) -> None:
        self.conn.execute("VACUUM")

    def admin_bootstrapped(self) -> bool:
        cur = self.conn.execute(
            """
            SELECT COUNT(*) AS n FROM users
            WHERE kind = 'admin' AND (disabled_at IS NULL OR disabled_at = '')
            """
        )
        row = cur.fetchone()
        return bool(row and int(row["n"]) > 0)

    def get_secret_meta(self, key: str) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM secrets_meta WHERE key = ?", (key,))
        row = cur.fetchone()
        if not row:
            return None
        return {
            "key": row["key"],
            "value_hash": row["value_hash"],
            "created_at": row["created_at"],
            "used_at": row["used_at"],
            "extra": _load(row["extra_json"], {}),
        }

    def upsert_secret_meta(self, key: str, value_hash: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        now = utc_now()
        existing = self.get_secret_meta(key)
        if existing and not existing.get("used_at"):
            self.conn.execute(
                """
                UPDATE secrets_meta
                SET value_hash = ?, created_at = ?, extra_json = ?
                WHERE key = ?
                """,
                (value_hash, now, _dump(extra or existing.get("extra") or {}), key),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO secrets_meta (key, value_hash, created_at, used_at, extra_json)
                VALUES (?, ?, ?, NULL, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_hash = excluded.value_hash,
                    created_at = excluded.created_at,
                    used_at = NULL,
                    extra_json = excluded.extra_json
                """,
                (key, value_hash, now, _dump(extra or {})),
            )
        self.conn.commit()
        stored = self.get_secret_meta(key)
        if stored is None:
            raise RuntimeError("secrets_meta upsert did not persist")
        return stored

    def mark_secret_used(self, key: str) -> None:
        self.conn.execute(
            "UPDATE secrets_meta SET used_at = ? WHERE key = ?",
            (utc_now(), key),
        )
        self.conn.commit()

    def create_admin(
        self,
        *,
        user_id: str,
        email: str,
        password_hash: str,
        display_name: str,
    ) -> dict[str, Any]:
        now = utc_now()
        self.conn.commit()
        self.conn.execute("BEGIN IMMEDIATE")
        cur = self.conn.execute(
            """
            SELECT COUNT(*) AS n FROM users
            WHERE kind = 'admin' AND (disabled_at IS NULL OR disabled_at = '')
            """
        )
        row = cur.fetchone()
        if row and int(row["n"]) > 0:
            self.conn.rollback()
            raise PermissionError("admin already bootstrapped")
        self.conn.execute(
            """
            INSERT INTO users (
                id, kind, track, email, password_hash, display_name,
                metadata_json, created_by, disabled_at, created_at
            ) VALUES (?, 'admin', NULL, ?, ?, ?, '{}', NULL, NULL, ?)
            """,
            (user_id, email, password_hash, display_name, now),
        )
        self.conn.commit()
        return {
            "id": user_id,
            "kind": "admin",
            "track": None,
            "email": email,
            "display_name": display_name,
            "created_at": now,
        }

    def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        token_hash: str,
        expires_at: str,
    ) -> dict[str, Any]:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO sessions (id, user_id, token_hash, expires_at, last_seen)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, user_id, token_hash, expires_at, now),
        )
        self.conn.commit()
        return {
            "id": session_id,
            "user_id": user_id,
            "expires_at": expires_at,
            "last_seen": now,
        }


def _owners(raw: Any) -> dict[str, str]:
    base = {"discovery": "", "apply": "", "outreach": ""}
    if isinstance(raw, dict):
        for key in base:
            if key in raw and raw[key] is not None:
                base[key] = str(raw[key])
    return base


def _remote_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
