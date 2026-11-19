"""A2A task and peer SQL. HTTP stays in app.a2a; a2a_store keeps the old function names."""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from app.tenant import account_id_of

TASK_LIST_DEFAULT_LIMIT = 50
TASK_LIST_MAX_LIMIT = 200
PEER_LIST_DEFAULT_LIMIT = 200

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS a2a_tasks (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
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
    account_id TEXT NOT NULL,
    name TEXT,
    card_url TEXT NOT NULL,
    agent_url TEXT,
    card_json TEXT,
    created_at TEXT NOT NULL,
    last_ok_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_a2a_peers_account_card
    ON a2a_peers(account_id, card_url);
"""

# Retire UNIQUE(card_url) from databases created before the index above.
# DROP CONSTRAINT keeps every row.
_DROP_CARD_URL_UNIQUE = "ALTER TABLE a2a_peers DROP CONSTRAINT IF EXISTS a2a_peers_card_url_key"

_CARD_URL_ONLY_UNIQUES = """
SELECT con.conname AS name
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
WHERE nsp.nspname = current_schema()
  AND rel.relname = 'a2a_peers'
  AND con.contype = 'u'
  AND array_length(con.conkey, 1) = 1
  AND (
    SELECT att.attname
    FROM pg_attribute att
    WHERE att.attrelid = rel.oid
      AND att.attnum = con.conkey[1]
  ) = 'card_url'
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


def ensure_a2a_schema(conn: Any) -> None:
    conn.executescript(SCHEMA)
    _drop_card_url_only_unique(conn)


def _drop_card_url_only_unique(conn: Any) -> None:
    """Uniqueness is (account_id, card_url). Do not delete peer rows."""
    if not hasattr(conn, "schema"):
        return
    conn.execute(_DROP_CARD_URL_UNIQUE)
    rows = conn.execute(_CARD_URL_ONLY_UNIQUES).fetchall()
    for row in rows:
        name = str(row["name"])
        if _IDENT.fullmatch(name) is None or name == "idx_a2a_peers_account_card":
            continue
        conn.execute(f"ALTER TABLE a2a_peers DROP CONSTRAINT {name}")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(16).replace("-", "").replace("_", "")[:26]


def _task_limit(limit: int) -> int:
    return max(1, min(int(limit), TASK_LIST_MAX_LIMIT))


def _peer_limit(limit: int | None) -> int:
    if limit is None:
        return PEER_LIST_DEFAULT_LIMIT
    return max(1, min(int(limit), PEER_LIST_DEFAULT_LIMIT))


def _task_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    request: Any = {}
    result: Any = {}
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


def _peer_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    card: Any = {}
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


class A2ARepo:
    """Tenant-scoped A2A tasks and peers. ``db`` is a BoardDB-like object with ``.conn``."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def insert_task(
        self,
        *,
        context_id: str | None = None,
        state: str = "submitted",
        skill_id: str | None = None,
        from_user_id: str | None = None,
        message_id: str | None = None,
        request: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        task_id: str | None = None,
        tenant: Any | None = None,
    ) -> dict[str, Any]:
        now = _now()
        tid = task_id or _new_id("task_")
        ctx = context_id or _new_id("ctx_")
        aid = account_id_of(tenant)
        self._db.conn.execute(
            """
            INSERT INTO a2a_tasks (
                id, account_id, context_id, state, skill_id, from_user_id, message_id,
                request_json, result_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tid,
                aid,
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
        self._db.conn.commit()
        stored = self.get_task(tid, tenant=tenant)
        assert stored is not None
        return stored

    def update_task(
        self,
        task_id: str,
        *,
        state: str | None = None,
        result: dict[str, Any] | None = None,
        message_id: str | None = None,
        tenant: Any | None = None,
    ) -> dict[str, Any] | None:
        """One UPDATE scoped by id and account. Omitted fields keep stored values."""
        result_json = None if result is None else json.dumps(result, ensure_ascii=False)
        row = self._db.conn.execute(
            """
            UPDATE a2a_tasks
               SET state = COALESCE(?, state),
                   result_json = COALESCE(?, result_json),
                   message_id = COALESCE(?, message_id),
                   updated_at = ?
             WHERE id = ? AND account_id = ?
            RETURNING *
            """,
            (
                state or None,
                result_json,
                message_id,
                _now(),
                task_id,
                account_id_of(tenant),
            ),
        ).fetchone()
        if row is None:
            rollback = getattr(self._db.conn, "rollback", None)
            if callable(rollback):
                rollback()
            return None
        self._db.conn.commit()
        return _task_row(row)

    def get_task(self, task_id: str, *, tenant: Any | None = None) -> dict[str, Any] | None:
        row = self._db.conn.execute(
            "SELECT * FROM a2a_tasks WHERE id = ? AND account_id = ?",
            (task_id, account_id_of(tenant)),
        ).fetchone()
        if row is None:
            return None
        return _task_row(row)

    def list_tasks(
        self,
        *,
        limit: int = TASK_LIST_DEFAULT_LIMIT,
        state: str | None = None,
        tenant: Any | None = None,
    ) -> list[dict[str, Any]]:
        limit = _task_limit(limit)
        aid = account_id_of(tenant)
        if state:
            cur = self._db.conn.execute(
                """
                SELECT * FROM a2a_tasks
                WHERE account_id = ? AND state = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (aid, state, limit),
            )
        else:
            cur = self._db.conn.execute(
                """
                SELECT * FROM a2a_tasks
                WHERE account_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (aid, limit),
            )
        return [_task_row(row) for row in cur.fetchall()]

    def insert_peer(
        self,
        *,
        name: str,
        card_url: str,
        agent_url: str | None,
        card: dict[str, Any],
        tenant: Any | None = None,
    ) -> dict[str, Any]:
        now = _now()
        peer_id = _new_id("peer_")
        self._db.conn.execute(
            """
            INSERT INTO a2a_peers (
                id, account_id, name, card_url, agent_url, card_json, created_at, last_ok_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                peer_id,
                account_id_of(tenant),
                name,
                card_url,
                agent_url,
                json.dumps(card, ensure_ascii=False),
                now,
                now,
            ),
        )
        self._db.conn.commit()
        stored = self.get_peer(peer_id, tenant=tenant)
        assert stored is not None
        return stored

    def get_peer(self, peer_id: str, *, tenant: Any | None = None) -> dict[str, Any] | None:
        row = self._db.conn.execute(
            "SELECT * FROM a2a_peers WHERE id = ? AND account_id = ?",
            (peer_id, account_id_of(tenant)),
        ).fetchone()
        if row is None:
            return None
        return _peer_row(row)

    def get_peer_by_card_url(
        self, card_url: str, *, tenant: Any | None = None
    ) -> dict[str, Any] | None:
        row = self._db.conn.execute(
            "SELECT * FROM a2a_peers WHERE card_url = ? AND account_id = ?",
            (card_url, account_id_of(tenant)),
        ).fetchone()
        if row is None:
            return None
        return _peer_row(row)

    def list_peers(
        self, *, tenant: Any | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        cur = self._db.conn.execute(
            """
            SELECT * FROM a2a_peers
            WHERE account_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (account_id_of(tenant), _peer_limit(limit)),
        )
        return [_peer_row(row) for row in cur.fetchall()]

    def touch_peer(self, peer_id: str, *, tenant: Any | None = None) -> None:
        self._db.conn.execute(
            "UPDATE a2a_peers SET last_ok_at = ? WHERE id = ? AND account_id = ?",
            (_now(), peer_id, account_id_of(tenant)),
        )
        self._db.conn.commit()
