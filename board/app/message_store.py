"""SQLite inbox rows. Router lives in messages.py; schema is applied from db migrate."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Protocol

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
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


def _new_id(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(16).replace("-", "").replace("_", "")[:26]


class InboxPrincipal(Protocol):
    role: str
    user_id: str | None
    track: str | None
    kind: str | None


class HasConn(Protocol):
    conn: Any

    def commit(self) -> None: ...


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_messages_schema(conn: Any) -> None:
    conn.executescript(SCHEMA)


def reader_key(principal: InboxPrincipal) -> str:
    if principal.user_id:
        return principal.user_id
    return f"compat:{principal.role}"


def sender_id(principal: InboxPrincipal) -> str:
    return principal.user_id or reader_key(principal)


def is_hub_admin(principal: InboxPrincipal) -> bool:
    return principal.kind == "admin" or principal.role == "admin"


def inbound_where(principal: InboxPrincipal) -> tuple[str, list[Any]]:
    if is_hub_admin(principal):
        return "1=1", []
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
        return "0=1", []
    return "(" + " OR ".join(clauses) + ")", args


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


def count_unread(db: HasConn, principal: InboxPrincipal) -> int:
    where, args = inbound_where(principal)
    key = reader_key(principal)
    cur = db.conn.execute(
        f"""
        SELECT COUNT(*) AS n FROM messages m
        WHERE {where}
          AND NOT EXISTS (
            SELECT 1 FROM message_reads r
            WHERE r.message_id = m.id AND r.reader_key = ?
          )
        """,
        [*args, key],
    )
    row = cur.fetchone()
    return int(row["n"]) if row else 0


def list_messages(
    db: HasConn,
    principal: InboxPrincipal,
    *,
    unread: bool = False,
    job_id: str | None = None,
    msg_type: str | None = None,
    sent: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    key = reader_key(principal)
    where, args = inbound_where(principal)
    if sent:
        if is_hub_admin(principal):
            where = "1=1"
            args = []
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
    sql = f"""
        SELECT messages.*,
               (SELECT r.read_at FROM message_reads r
                WHERE r.message_id = messages.id AND r.reader_key = ?) AS mine_read_at
        FROM messages
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
    """
    cur = db.conn.execute(sql, [key, *args, limit])
    out: list[dict[str, Any]] = []
    for row in cur.fetchall():
        mine = row["mine_read_at"]
        out.append(row_to_message(row, read=bool(mine)))
    return out


def insert_message(
    db: HasConn,
    *,
    from_user_id: str,
    to_user_id: str | None,
    to_track: str | None,
    job_id: str | None,
    msg_type: str,
    body: str,
) -> dict[str, Any]:
    now = _now()
    msg_id = _new_id("msg_")
    db.conn.execute(
        """
        INSERT INTO messages (
            id, from_user_id, to_user_id, to_track, job_id, type, body, created_at, read_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (msg_id, from_user_id, to_user_id, to_track, job_id or None, msg_type, body, now),
    )
    db.conn.commit()
    cur = db.conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("message insert did not persist")
    return row_to_message(row, read=False)


def get_message(db: HasConn, msg_id: str) -> dict[str, Any] | None:
    cur = db.conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,))
    row = cur.fetchone()
    if row is None:
        return None
    return dict(row)


class MessageNotFound(KeyError):
    pass


class MessageForbidden(PermissionError):
    pass


def mark_read(db: HasConn, principal: InboxPrincipal, msg_id: str) -> dict[str, Any]:
    stored = get_message(db, msg_id)
    if stored is None:
        raise MessageNotFound(msg_id)
    if not can_see(principal, stored):
        raise MessageForbidden(msg_id)
    now = _now()
    key = reader_key(principal)
    db.conn.execute(
        """
        INSERT INTO message_reads (message_id, reader_key, read_at)
        VALUES (?, ?, ?)
        ON CONFLICT(message_id, reader_key) DO UPDATE SET read_at = excluded.read_at
        """,
        (msg_id, key, now),
    )
    if not stored.get("read_at"):
        db.conn.execute(
            "UPDATE messages SET read_at = ? WHERE id = ? AND read_at IS NULL",
            (now, msg_id),
        )
    db.conn.commit()
    fresh = get_message(db, msg_id)
    if fresh is None:
        raise RuntimeError("message vanished")
    return row_to_message(fresh, read=True)
