"""A2A tasks and federated peer Agent Cards. Schema is applied from db migrate."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any, Protocol

SCHEMA = """
CREATE TABLE IF NOT EXISTS a2a_tasks (
    id TEXT PRIMARY KEY,
    context_id TEXT NOT NULL,
    state TEXT NOT NULL,
    skill_id TEXT,
    from_user_id TEXT,
    message_id TEXT,
    request_json TEXT,
    result_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_a2a_tasks_context ON a2a_tasks(context_id);
CREATE INDEX IF NOT EXISTS idx_a2a_tasks_state ON a2a_tasks(state);

CREATE TABLE IF NOT EXISTS a2a_peers (
    id TEXT PRIMARY KEY,
    name TEXT,
    card_url TEXT NOT NULL UNIQUE,
    agent_url TEXT,
    card_json TEXT,
    created_at TEXT NOT NULL,
    last_ok_at TEXT
);
"""

TASK_STATES = (
    "submitted",
    "working",
    "input-required",
    "completed",
    "canceled",
    "failed",
    "rejected",
    "auth-required",
    "unknown",
)


class HasConn(Protocol):
    conn: Any

    def commit(self) -> None: ...


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(16).replace("-", "").replace("_", "")[:26]


def ensure_a2a_schema(conn: Any) -> None:
    conn.executescript(SCHEMA)


def insert_task(
    db: HasConn,
    *,
    context_id: str | None = None,
    state: str = "submitted",
    skill_id: str | None = None,
    from_user_id: str | None = None,
    message_id: str | None = None,
    request: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    now = _now()
    tid = task_id or _new_id("task_")
    ctx = context_id or _new_id("ctx_")
    db.conn.execute(
        """
        INSERT INTO a2a_tasks (
            id, context_id, state, skill_id, from_user_id, message_id,
            request_json, result_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tid,
            ctx,
            state,
            skill_id,
            from_user_id,
            message_id,
            json.dumps(request or {}, ensure_ascii=False),
            json.dumps(result or {}, ensure_ascii=False),
            now,
            now,
        ),
    )
    db.conn.commit()
    stored = get_task(db, tid)
    assert stored is not None
    return stored


def update_task(
    db: HasConn,
    task_id: str,
    *,
    state: str | None = None,
    result: dict[str, Any] | None = None,
    message_id: str | None = None,
) -> dict[str, Any] | None:
    stored = get_task(db, task_id)
    if stored is None:
        return None
    now = _now()
    next_state = state or stored["state"]
    result_json = json.dumps(result if result is not None else stored.get("result") or {}, ensure_ascii=False)
    next_message = message_id if message_id is not None else stored.get("message_id")
    db.conn.execute(
        """
        UPDATE a2a_tasks
           SET state = ?, result_json = ?, message_id = ?, updated_at = ?
         WHERE id = ?
        """,
        (next_state, result_json, next_message, now, task_id),
    )
    db.conn.commit()
    return get_task(db, task_id)


def get_task(db: HasConn, task_id: str) -> dict[str, Any] | None:
    cur = db.conn.execute("SELECT * FROM a2a_tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    if row is None:
        return None
    return _task_row(row)


def list_tasks(db: HasConn, *, limit: int = 50, state: str | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    if state:
        cur = db.conn.execute(
            "SELECT * FROM a2a_tasks WHERE state = ? ORDER BY created_at DESC LIMIT ?",
            (state, limit),
        )
    else:
        cur = db.conn.execute(
            "SELECT * FROM a2a_tasks ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    return [_task_row(row) for row in cur.fetchall()]


def _task_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    request = {}
    result = {}
    try:
        request = json.loads(data.get("request_json") or "{}")
    except json.JSONDecodeError:
        request = {}
    try:
        result = json.loads(data.get("result_json") or "{}")
    except json.JSONDecodeError:
        result = {}
    return {
        "id": data["id"],
        "context_id": data["context_id"],
        "state": data["state"],
        "skill_id": data.get("skill_id"),
        "from_user_id": data.get("from_user_id"),
        "message_id": data.get("message_id"),
        "request": request,
        "result": result,
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }


def insert_peer(
    db: HasConn,
    *,
    name: str,
    card_url: str,
    agent_url: str | None,
    card: dict[str, Any],
) -> dict[str, Any]:
    now = _now()
    peer_id = _new_id("peer_")
    db.conn.execute(
        """
        INSERT INTO a2a_peers (id, name, card_url, agent_url, card_json, created_at, last_ok_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            peer_id,
            name,
            card_url,
            agent_url,
            json.dumps(card, ensure_ascii=False),
            now,
            now,
        ),
    )
    db.conn.commit()
    stored = get_peer(db, peer_id)
    assert stored is not None
    return stored


def get_peer(db: HasConn, peer_id: str) -> dict[str, Any] | None:
    cur = db.conn.execute("SELECT * FROM a2a_peers WHERE id = ?", (peer_id,))
    row = cur.fetchone()
    if row is None:
        return None
    return _peer_row(row)


def get_peer_by_card_url(db: HasConn, card_url: str) -> dict[str, Any] | None:
    cur = db.conn.execute("SELECT * FROM a2a_peers WHERE card_url = ?", (card_url,))
    row = cur.fetchone()
    if row is None:
        return None
    return _peer_row(row)


def list_peers(db: HasConn) -> list[dict[str, Any]]:
    cur = db.conn.execute("SELECT * FROM a2a_peers ORDER BY created_at DESC")
    return [_peer_row(row) for row in cur.fetchall()]


def touch_peer(db: HasConn, peer_id: str) -> None:
    db.conn.execute(
        "UPDATE a2a_peers SET last_ok_at = ? WHERE id = ?",
        (_now(), peer_id),
    )
    db.conn.commit()


def _peer_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    card: dict[str, Any] = {}
    try:
        card = json.loads(data.get("card_json") or "{}")
    except json.JSONDecodeError:
        card = {}
    return {
        "id": data["id"],
        "name": data.get("name") or "",
        "card_url": data["card_url"],
        "agent_url": data.get("agent_url"),
        "card": card,
        "created_at": data["created_at"],
        "last_ok_at": data.get("last_ok_at"),
    }
