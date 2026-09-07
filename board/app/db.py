"""SQLite store for jobs + append-only events."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.constants import JSON_FIELDS, STATUSES
from app.message_store import ensure_messages_schema

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
    csrf_hash TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);

CREATE TABLE IF NOT EXISTS invites (
    id TEXT PRIMARY KEY,
    track TEXT NOT NULL,
    mode TEXT NOT NULL,
    secret_hash TEXT NOT NULL,
    max_redemptions INTEGER NOT NULL,
    redemptions INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_by TEXT,
    allow_multiple_owners INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_invites_track ON invites(track);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_track_display
    ON users(track, display_name)
    WHERE track IS NOT NULL AND display_name IS NOT NULL
      AND (disabled_at IS NULL OR disabled_at = '');

CREATE TABLE IF NOT EXISTS queue_items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    track TEXT,
    job_id TEXT,
    payload_json TEXT,
    status TEXT NOT NULL,
    claimed_by TEXT,
    lease_until TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    dedupe_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_queue_status_kind ON queue_items(status, kind);
CREATE INDEX IF NOT EXISTS idx_queue_claimed_by ON queue_items(claimed_by);
CREATE INDEX IF NOT EXISTS idx_queue_job ON queue_items(job_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_kind_job
    ON queue_items(kind, job_id)
    WHERE job_id IS NOT NULL AND job_id != '';
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
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    session_cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "csrf_hash" not in session_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN csrf_hash TEXT")
    invite_cols = {row[1] for row in conn.execute("PRAGMA table_info(invites)").fetchall()}
    if invite_cols and "allow_multiple_owners" not in invite_cols:
        conn.execute(
            "ALTER TABLE invites ADD COLUMN allow_multiple_owners INTEGER NOT NULL DEFAULT 0"
        )
    ensure_messages_schema(conn)


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
        csrf_hash: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO sessions (id, user_id, token_hash, expires_at, last_seen, csrf_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, user_id, token_hash, expires_at, now, csrf_hash),
        )
        self.conn.commit()
        return {
            "id": session_id,
            "user_id": user_id,
            "expires_at": expires_at,
            "last_seen": now,
        }

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        return _row_to_user(row) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        cur = self.conn.execute(
            "SELECT * FROM users WHERE lower(email) = lower(?) AND email IS NOT NULL AND email != ''",
            (email.strip(),),
        )
        row = cur.fetchone()
        return _row_to_user(row) if row else None

    def list_users(
        self,
        *,
        track: str | None = None,
        kind: str | None = None,
        include_disabled: bool = False,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        args: list[Any] = []
        if track:
            clauses.append("track = ?")
            args.append(track)
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        if not include_disabled:
            clauses.append("(disabled_at IS NULL OR disabled_at = '')")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = self.conn.execute(f"SELECT * FROM users {where} ORDER BY created_at", args)
        return [_row_to_user(r) for r in cur.fetchall()]

    def count_owners(self, track: str) -> int:
        cur = self.conn.execute(
            """
            SELECT COUNT(*) AS n FROM users
            WHERE track = ? AND kind = 'owner' AND (disabled_at IS NULL OR disabled_at = '')
            """,
            (track,),
        )
        row = cur.fetchone()
        return int(row["n"]) if row else 0

    def display_name_taken(self, track: str, display_name: str, exclude_id: str | None = None) -> bool:
        cur = self.conn.execute(
            """
            SELECT id FROM users
            WHERE track = ? AND lower(display_name) = lower(?)
              AND (disabled_at IS NULL OR disabled_at = '')
            """,
            (track, display_name.strip()),
        )
        row = cur.fetchone()
        if not row:
            return False
        return row["id"] != exclude_id

    def insert_user(
        self,
        *,
        user_id: str,
        kind: str,
        track: str | None,
        email: str | None,
        password_hash: str | None,
        display_name: str,
        metadata: dict[str, Any] | None,
        created_by: str | None,
        commit: bool = True,
    ) -> dict[str, Any]:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO users (
                id, kind, track, email, password_hash, display_name,
                metadata_json, created_by, disabled_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                user_id,
                kind,
                track,
                (email or "").strip().lower() or None,
                password_hash,
                display_name.strip(),
                _dump(metadata or {}),
                created_by,
                now,
            ),
        )
        if commit:
            self.conn.commit()
        stored = self.get_user(user_id)
        if stored is None:
            raise RuntimeError("user insert did not persist")
        return stored

    def disable_user(self, user_id: str) -> dict[str, Any]:
        now = utc_now()
        self.conn.execute(
            "UPDATE users SET disabled_at = ? WHERE id = ?",
            (now, user_id),
        )
        self.conn.commit()
        stored = self.get_user(user_id)
        if stored is None:
            raise KeyError(user_id)
        return stored

    def update_user_metadata(self, user_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        self.conn.execute(
            "UPDATE users SET metadata_json = ? WHERE id = ?",
            (_dump(metadata), user_id),
        )
        self.conn.commit()
        stored = self.get_user(user_id)
        if stored is None:
            raise KeyError(user_id)
        return stored

    def get_session_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        cur = self.conn.execute(
            "SELECT * FROM sessions WHERE token_hash = ?",
            (token_hash,),
        )
        row = cur.fetchone()
        return _row_to_session(row) if row else None

    def delete_session(self, session_id: str) -> None:
        self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self.conn.commit()

    def touch_session(self, session_id: str, expires_at: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET last_seen = ?, expires_at = ? WHERE id = ?",
            (utc_now(), expires_at, session_id),
        )
        self.conn.commit()

    def insert_api_key(
        self,
        *,
        key_id: str,
        user_id: str,
        prefix: str,
        key_hash: str,
        commit: bool = True,
    ) -> dict[str, Any]:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO api_keys (id, user_id, prefix, key_hash, created_at, revoked_at)
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (key_id, user_id, prefix, key_hash, now),
        )
        if commit:
            self.conn.commit()
        return {
            "id": key_id,
            "user_id": user_id,
            "prefix": prefix,
            "created_at": now,
        }

    def get_api_key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,))
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "prefix": row["prefix"],
            "key_hash": row["key_hash"],
            "created_at": row["created_at"],
            "revoked_at": row["revoked_at"],
        }

    def revoke_api_key(self, key_id: str) -> None:
        self.conn.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (utc_now(), key_id),
        )
        self.conn.commit()

    def revoke_user_keys(self, user_id: str) -> None:
        self.conn.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (utc_now(), user_id),
        )
        self.conn.commit()

    def active_key_for_user(self, user_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute(
            """
            SELECT * FROM api_keys
            WHERE user_id = ? AND revoked_at IS NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "prefix": row["prefix"],
            "created_at": row["created_at"],
        }

    def insert_invite(
        self,
        *,
        invite_id: str,
        track: str,
        mode: str,
        secret_hash: str,
        max_redemptions: int,
        expires_at: str,
        created_by: str | None,
        allow_multiple_owners: bool,
    ) -> dict[str, Any]:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO invites (
                id, track, mode, secret_hash, max_redemptions, redemptions,
                expires_at, revoked_at, created_by, allow_multiple_owners, created_at
            ) VALUES (?, ?, ?, ?, ?, 0, ?, NULL, ?, ?, ?)
            """,
            (
                invite_id,
                track,
                mode,
                secret_hash,
                max_redemptions,
                expires_at,
                created_by,
                1 if allow_multiple_owners else 0,
                now,
            ),
        )
        self.conn.commit()
        stored = self.get_invite(invite_id)
        if stored is None:
            raise RuntimeError("invite insert did not persist")
        return stored

    def get_invite(self, invite_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM invites WHERE id = ?", (invite_id,))
        row = cur.fetchone()
        return _row_to_invite(row) if row else None

    def list_invites(self) -> list[dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM invites ORDER BY created_at DESC")
        return [_row_to_invite(r) for r in cur.fetchall()]

    def revoke_invite(self, invite_id: str) -> dict[str, Any]:
        self.conn.execute(
            "UPDATE invites SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (utc_now(), invite_id),
        )
        self.conn.commit()
        stored = self.get_invite(invite_id)
        if stored is None:
            raise KeyError(invite_id)
        return stored

    def expire_invite(self, invite_id: str, expires_at: str) -> None:
        self.conn.execute(
            "UPDATE invites SET expires_at = ? WHERE id = ?",
            (expires_at, invite_id),
        )
        self.conn.commit()

    def redeem_invite(self, invite_id: str, *, commit: bool = True) -> dict[str, Any]:
        self.conn.execute(
            "UPDATE invites SET redemptions = redemptions + 1 WHERE id = ?",
            (invite_id,),
        )
        if commit:
            self.conn.commit()
        stored = self.get_invite(invite_id)
        if stored is None:
            raise KeyError(invite_id)
        return stored

    def begin_immediate(self) -> None:
        self.conn.commit()
        self.conn.execute("BEGIN IMMEDIATE")

    def rollback(self) -> None:
        self.conn.rollback()


def _row_to_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "track": row["track"],
        "email": row["email"],
        "password_hash": row["password_hash"],
        "display_name": row["display_name"] or "",
        "metadata": _load(row["metadata_json"], {}),
        "created_by": row["created_by"],
        "disabled_at": row["disabled_at"],
        "created_at": row["created_at"],
    }


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "kind": user["kind"],
        "track": user.get("track"),
        "email": user.get("email"),
        "display_name": user.get("display_name") or "",
        "metadata": user.get("metadata") or {},
        "created_by": user.get("created_by"),
        "disabled_at": user.get("disabled_at"),
        "created_at": user.get("created_at"),
    }


def _row_to_session(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "token_hash": row["token_hash"],
        "expires_at": row["expires_at"],
        "last_seen": row["last_seen"],
        "csrf_hash": row["csrf_hash"] if "csrf_hash" in keys else None,
    }


def _row_to_invite(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "track": row["track"],
        "mode": row["mode"],
        "secret_hash": row["secret_hash"],
        "max_redemptions": int(row["max_redemptions"]),
        "redemptions": int(row["redemptions"]),
        "expires_at": row["expires_at"],
        "revoked_at": row["revoked_at"],
        "created_by": row["created_by"],
        "allow_multiple_owners": bool(row["allow_multiple_owners"]),
        "created_at": row["created_at"],
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
