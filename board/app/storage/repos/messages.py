"""Inbox SQL. HTTP stays in app.messages; message_store keeps the old function names."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Protocol

from app.tenant import account_id_of

LIST_DEFAULT_LIMIT = 100
LIST_MAX_LIMIT = 500

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    from_user_id TEXT,
    to_user_id TEXT,
    to_track TEXT,
    job_id TEXT,
    type TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_to_user ON messages(to_user_id);
CREATE INDEX IF NOT EXISTS idx_messages_to_track ON messages(to_track);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);

CREATE TABLE IF NOT EXISTS message_reads (
    message_id TEXT NOT NULL,
    reader_key TEXT NOT NULL,
    read_at TEXT NOT NULL,
    PRIMARY KEY (message_id, reader_key)
);

CREATE INDEX IF NOT EXISTS idx_message_reads_reader ON message_reads(reader_key);
"""


class InboxPrincipal(Protocol):
    role: str
    user_id: str | None
    track: str | None
    kind: str | None


class MessageNotFound(KeyError):
    pass


class MessageForbidden(PermissionError):
    pass


def ensure_messages_schema(conn: Any) -> None:
    conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(16).replace("-", "").replace("_", "")[:26]


def _list_limit(limit: int) -> int:
    return max(1, min(int(limit), LIST_MAX_LIMIT))


def reader_key(principal: InboxPrincipal) -> str:
    if principal.user_id:
        return principal.user_id
    return f"compat:{principal.role}"


def sender_id(principal: InboxPrincipal) -> str:
    return principal.user_id or reader_key(principal)


def is_hub_admin(principal: InboxPrincipal) -> bool:
    return principal.kind == "admin" or principal.role == "admin"


def inbound_where(principal: InboxPrincipal) -> tuple[str, list[Any]]:
    aid = account_id_of(principal)
    if is_hub_admin(principal):
        return "account_id = ?", [aid]
    clauses: list[str] = []
    args: list[Any] = []
    if principal.user_id:
        clauses.append("to_user_id = ?")
        args.append(principal.user_id)
    track = principal.track
    if track:
        clauses.append("to_track = ?")
        args.append(track)
    if not clauses:
        return "account_id = ? AND 0=1", [aid]
    return "account_id = ? AND (" + " OR ".join(clauses) + ")", [aid, *args]


def can_see(principal: InboxPrincipal, row: dict[str, Any]) -> bool:
    if is_hub_admin(principal):
        return True
    if principal.user_id and row.get("to_user_id") == principal.user_id:
        return True
    if principal.track and row.get("to_track") == principal.track:
        return True
    return False


def row_to_message(row: Any, *, read: bool) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": data["id"],
        "from_user_id": data["from_user_id"] or "",
        "to_user_id": data["to_user_id"] or None,
        "to_track": data["to_track"] or None,
        "job_id": data["job_id"] or None,
        "type": data["type"],
        "body": data["body"],
        "created_at": data["created_at"],
        "read_at": data["read_at"],
        "read": read,
    }


class MessageRepo:
    """Tenant-scoped inbox rows. ``db`` is a BoardDB-like object with ``.conn``."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def count_unread(self, principal: InboxPrincipal) -> int:
        where, args = inbound_where(principal)
        row = self._db.conn.execute(
            f"""
            SELECT COUNT(*) AS n FROM messages m
            WHERE {where}
              AND NOT EXISTS (
                SELECT 1 FROM message_reads r
                WHERE r.message_id = m.id AND r.reader_key = ?
              )
            """,
            [*args, reader_key(principal)],
        ).fetchone()
        return int(row["n"]) if row else 0

    def list_messages(
        self,
        principal: InboxPrincipal,
        *,
        unread: bool = False,
        job_id: str | None = None,
        msg_type: str | None = None,
        sent: bool = False,
        limit: int = LIST_DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        limit = _list_limit(limit)
        key = reader_key(principal)
        where, args = inbound_where(principal)
        if sent:
            if is_hub_admin(principal):
                where = "account_id = ?"
                args = [account_id_of(principal)]
            else:
                where = f"({where} OR from_user_id = ?)"
                args = [*args, sender_id(principal)]
        clauses = [where]
        if unread:
            clauses.append(
                """NOT EXISTS (
                    SELECT 1 FROM message_reads r
                    WHERE r.message_id = messages.id AND r.reader_key = ?
                )"""
            )
            args.append(key)
        if job_id:
            clauses.append("job_id = ?")
            args.append(job_id)
        if msg_type:
            clauses.append("type = ?")
            args.append(msg_type)
        cur = self._db.conn.execute(
            f"""
            SELECT messages.*,
                   (SELECT r.read_at FROM message_reads r
                    WHERE r.message_id = messages.id AND r.reader_key = ?) AS mine_read_at
            FROM messages
            WHERE {" AND ".join(clauses)}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            [key, *args, limit],
        )
        out: list[dict[str, Any]] = []
        for row in cur.fetchall():
            out.append(row_to_message(row, read=bool(row["mine_read_at"])))
        return out

    def insert_message(
        self,
        *,
        from_user_id: str,
        to_user_id: str | None,
        to_track: str | None,
        job_id: str | None,
        msg_type: str,
        body: str,
        principal: InboxPrincipal | None = None,
    ) -> dict[str, Any]:
        now = _now()
        msg_id = _new_id("msg_")
        account_id = account_id_of(principal)
        self._db.conn.execute(
            """
            INSERT INTO messages (
                id, account_id, from_user_id, to_user_id, to_track, job_id, type, body, created_at, read_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                msg_id,
                account_id,
                from_user_id,
                to_user_id,
                to_track,
                job_id or None,
                msg_type,
                body,
                now,
            ),
        )
        self._db.conn.commit()
        row = self._db.conn.execute(
            "SELECT * FROM messages WHERE id = ? AND account_id = ?",
            (msg_id, account_id),
        ).fetchone()
        if row is None:
            raise RuntimeError("message insert did not persist")
        return row_to_message(row, read=False)

    def get_message(
        self, msg_id: str, *, principal: InboxPrincipal | None = None
    ) -> dict[str, Any] | None:
        row = self._db.conn.execute(
            "SELECT * FROM messages WHERE id = ? AND account_id = ?",
            (msg_id, account_id_of(principal)),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def mark_read(self, principal: InboxPrincipal, msg_id: str) -> dict[str, Any]:
        stored = self.get_message(msg_id, principal=principal)
        if stored is None:
            raise MessageNotFound(msg_id)
        if not can_see(principal, stored):
            raise MessageForbidden(msg_id)
        now = _now()
        self._db.conn.execute(
            """
            INSERT INTO message_reads (message_id, reader_key, read_at)
            VALUES (?, ?, ?)
            ON CONFLICT(message_id, reader_key) DO UPDATE SET read_at = excluded.read_at
            """,
            (msg_id, reader_key(principal), now),
        )
        if not stored.get("read_at"):
            self._db.conn.execute(
                "UPDATE messages SET read_at = ? WHERE id = ? AND read_at IS NULL",
                (now, msg_id),
            )
        self._db.conn.commit()
        fresh = self.get_message(msg_id, principal=principal)
        if fresh is None:
            raise RuntimeError("message vanished")
        return row_to_message(fresh, read=True)
