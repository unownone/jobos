"""Presence table reads and writes.

The directory list stays account-scoped and newest-heartbeat first:

    SELECT * FROM presence WHERE account_id = ? ORDER BY last_heartbeat DESC

That predicate needs a composite index. Migrations own DDL, so this module
does not create it:

    CREATE INDEX IF NOT EXISTS idx_presence_account_last_heartbeat
        ON presence (account_id, last_heartbeat DESC);

``load_users_by_ids`` and ``actors_with_events_since`` each issue one SELECT
per parameter chunk. Callers listing a directory must use those, not one
``get_user`` or ``SELECT 1 ... LIMIT 1`` per row.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Protocol, Sequence

from app.storage.dialect import Dialect, chunked_in
from app.storage.port import Database, QueryCounter, Result, Stmt
from app.tenant import COMPAT_ACCOUNT_ID

LIST_PRESENCE_SQL = (
    "SELECT * FROM presence WHERE account_id = ? ORDER BY last_heartbeat DESC"
)


class _SupportsExecute(Protocol):
    def execute(self, sql: str, params: Any = ()) -> Any:
        """Return a cursor with fetchall()."""


def presence_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(row)
    return {
        "user_id": data["user_id"],
        "status": data.get("status") or "",
        "status_hint": data.get("status_hint") or "",
        "last_heartbeat": data["last_heartbeat"],
        "connected_at": data["connected_at"],
        "task_id": data.get("task_id") or None,
        "task_kind": data.get("task_kind") or None,
        "job_id": data.get("job_id") or None,
        "producing": bool(data.get("producing")),
        "producing_at": data.get("producing_at") or None,
        "user_agent": data.get("user_agent") or "",
    }


def user_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Same public user shape BoardDB.get_user returns from a users row."""
    data = dict(row)
    raw_meta = data.get("metadata_json")
    if isinstance(raw_meta, dict):
        metadata = raw_meta
    elif raw_meta is None or raw_meta == "":
        metadata = {}
    else:
        loaded = json.loads(raw_meta)
        metadata = loaded if isinstance(loaded, dict) else {}
    return {
        "id": data["id"],
        "account_id": data.get("account_id") or COMPAT_ACCOUNT_ID,
        "kind": data["kind"],
        "track": data.get("track"),
        "email": data.get("email"),
        "password_hash": data.get("password_hash"),
        "display_name": data.get("display_name") or "",
        "metadata": metadata,
        "created_by": data.get("created_by"),
        "disabled_at": data.get("disabled_at"),
        "created_at": data.get("created_at"),
    }


def _unique(values: Sequence[Any]) -> list[Any]:
    chosen: list[Any] = []
    seen: set[Any] = set()
    for value in values:
        if value is None or value == "":
            continue
        if value in seen:
            continue
        seen.add(value)
        chosen.append(value)
    return chosen


def _qmark_dialect(dialect: Dialect) -> Dialect:
    """Repository SQL uses ``?``. Chunking still honors the engine's param cap."""
    if dialect.placeholder == "?":
        return dialect
    return Dialect(
        name=dialect.name,
        placeholder="?",
        max_params=dialect.max_params,
        skip_locked=dialect.skip_locked,
    )


class ConnDatabase:
    """Adapt BoardDB's qmark connection to the storage port.

    The Hub connection rewrites ``?`` and commits explicitly. SqliteDatabase
    already implements Database and should be passed through directly.
    """

    def __init__(self, conn: _SupportsExecute) -> None:
        self._conn = conn
        self.dialect = Dialect(name="qmark", placeholder="?", max_params=100, skip_locked=None)
        self.queries = QueryCounter()

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> Mapping[str, Any] | None:
        rows = self.fetch_all(sql, params)
        if not rows:
            return None
        return rows[0]

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[Mapping[str, Any]]:
        return list(self.execute(sql, params).rows)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Result:
        self.queries.add(1)
        cursor = self._conn.execute(sql, tuple(params))
        fetched = cursor.fetchall()
        rows = tuple(dict(row) for row in fetched)
        rowcount = cursor.rowcount if getattr(cursor, "rowcount", None) is not None else -1
        return Result(rowcount=rowcount, last_id=getattr(cursor, "lastrowid", None), rows=rows)

    def batch(self, stmts: Sequence[Stmt]) -> list[Result]:
        results = [self.execute(stmt.sql, stmt.params) for stmt in stmts]
        self.commit()
        return results

    def commit(self) -> None:
        commit = getattr(self._conn, "commit", None)
        if callable(commit):
            commit()


def _is_database(source: Any) -> bool:
    return all(hasattr(source, name) for name in ("fetch_all", "execute", "dialect", "queries"))


def presence_repo(source: Any) -> PresenceRepo:
    """Build a repo from a Database, a BoardDB, or a qmark connection."""
    if isinstance(source, PresenceRepo):
        return source
    if _is_database(source):
        return PresenceRepo(source)
    conn = getattr(source, "conn", None)
    if conn is None and hasattr(source, "execute"):
        conn = source
    if conn is None:
        raise TypeError("presence repo needs a Database or a connection")
    return PresenceRepo(ConnDatabase(conn))


class PresenceRepo:
    """SQL for presence rows, batched user loads, and batched event probes."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get_row(self, user_id: str) -> dict[str, Any] | None:
        row = self._db.fetch_one("SELECT * FROM presence WHERE user_id = ?", (user_id,))
        if row is None:
            return None
        return presence_from_row(row)

    def list_rows(self, account_id: str) -> list[dict[str, Any]]:
        """Newest heartbeat first. See the module docstring for the index."""
        rows = self._db.fetch_all(LIST_PRESENCE_SQL, (account_id,))
        return [presence_from_row(row) for row in rows]

    def upsert(
        self,
        *,
        user_id: str,
        status: str,
        status_hint: str | None,
        last_heartbeat: str,
        connected_at: str,
        task_id: str | None,
        task_kind: str | None,
        job_id: str | None,
        producing: bool,
        producing_at: str | None,
        user_agent: str | None,
        account_id: str,
    ) -> dict[str, Any]:
        self._db.execute(
            """
            INSERT INTO presence (
                user_id, account_id, status, status_hint, last_heartbeat, connected_at,
                task_id, task_kind, job_id, producing, producing_at, user_agent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                account_id = excluded.account_id,
                status = excluded.status,
                status_hint = excluded.status_hint,
                last_heartbeat = excluded.last_heartbeat,
                connected_at = excluded.connected_at,
                task_id = excluded.task_id,
                task_kind = excluded.task_kind,
                job_id = excluded.job_id,
                producing = excluded.producing,
                producing_at = excluded.producing_at,
                user_agent = excluded.user_agent
            """,
            (
                user_id,
                account_id,
                status,
                status_hint,
                last_heartbeat,
                connected_at,
                task_id,
                task_kind,
                job_id,
                1 if producing else 0,
                producing_at,
                user_agent or "",
            ),
        )
        commit = getattr(self._db, "commit", None)
        if callable(commit):
            commit()
        stored = self.get_row(user_id)
        if stored is None:
            raise RuntimeError("presence upsert did not persist")
        return stored

    def list_recent_sessions(self, since: str, account_id: str) -> list[dict[str, Any]]:
        rows = self._db.fetch_all(
            """
            SELECT s.id, s.user_id, s.last_seen, s.expires_at
            FROM sessions s
            WHERE s.last_seen >= ? AND s.account_id = ?
            ORDER BY s.last_seen DESC
            """,
            (since, account_id),
        )
        return [
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "last_seen": row["last_seen"],
                "expires_at": row["expires_at"],
            }
            for row in rows
        ]

    def load_users_by_ids(self, user_ids: Sequence[Any]) -> dict[str, dict[str, Any]]:
        """One ``SELECT ... WHERE id IN (...)`` per chunk. No per-id lookup."""
        ids = _unique(user_ids)
        if not ids:
            return {}
        found: dict[str, dict[str, Any]] = {}
        dialect = _qmark_dialect(self._db.dialect)
        for clause, params in chunked_in(dialect, "id", ids, reserved=0):
            rows = self._db.fetch_all(f"SELECT * FROM users WHERE {clause}", params)
            for row in rows:
                user = user_from_row(row)
                found[str(user["id"])] = user
        return found

    def actors_with_events_since(
        self,
        account_id: str,
        since: str,
        actors: Sequence[Any],
    ) -> set[Any]:
        """Actors with a non-empty job_id event at or after ``since``.

        One SELECT per chunk. This replaces ``SELECT 1 ... LIMIT 1`` per user.
        """
        chosen = _unique(actors)
        if not chosen:
            return set()
        found: set[Any] = set()
        dialect = _qmark_dialect(self._db.dialect)
        for clause, params in chunked_in(dialect, "actor", chosen, reserved=2):
            rows = self._db.fetch_all(
                f"""
                SELECT DISTINCT actor FROM events
                WHERE account_id = ?
                  AND ts >= ?
                  AND {clause}
                  AND job_id IS NOT NULL
                  AND TRIM(job_id) != ''
                """,
                (account_id, since, *params),
            )
            for row in rows:
                actor = row.get("actor") if isinstance(row, Mapping) else None
                if actor:
                    found.add(actor)
        return found


def load_users_by_ids(db: Any, user_ids: Sequence[Any]) -> dict[str, dict[str, Any]]:
    """Load many users by id. Query count follows chunks, not ``len(user_ids)``."""
    return presence_repo(db).load_users_by_ids(user_ids)
