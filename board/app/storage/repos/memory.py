"""SQL for memory items.

Callers pass the same DB-API connection ``memory_store`` already holds
(``db.conn``). This module does not commit.
"""

from __future__ import annotations

from typing import Any, Sequence

from app.memory_policy import (
    POD_COMMON,
    POD_KIND_COMMON,
    POD_KIND_TRACK,
    POD_KIND_WORKER,
    search_like_pattern,
)
from app.sql import column_names as sql_column_names

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    pod TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    job_id TEXT,
    company TEXT,
    tags_json TEXT,
    importance INTEGER NOT NULL DEFAULT 2,
    pinned INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_track TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    last_recalled_at TEXT,
    recall_count INTEGER NOT NULL DEFAULT 0,
    solidify_status TEXT NOT NULL DEFAULT 'none',
    recording_id TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_account_pod_hash
    ON memory_items(account_id, pod, content_hash);
CREATE INDEX IF NOT EXISTS idx_memory_pod ON memory_items(pod);
CREATE INDEX IF NOT EXISTS idx_memory_kind ON memory_items(kind);
CREATE INDEX IF NOT EXISTS idx_memory_expires ON memory_items(expires_at);
CREATE INDEX IF NOT EXISTS idx_memory_created_by ON memory_items(created_by, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_recording ON memory_items(recording_id);
"""

LIVE_CLAUSE = "(expires_at IS NULL OR expires_at = '' OR expires_at > ?)"
_LIKE_FIELDS = (
    "(title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\' "
    "OR COALESCE(company, '') LIKE ? ESCAPE '\\')"
)
TOUCH_BIND_BUDGET = 90
_TOUCH_FIXED_BINDS = 2


def ensure_schema(conn: Any) -> None:
    conn.executescript(SCHEMA)
    cols = _column_names(conn, "memory_items")
    if "solidify_status" not in cols:
        conn.execute(
            "ALTER TABLE memory_items ADD COLUMN solidify_status TEXT NOT NULL DEFAULT 'none'"
        )
    if "recording_id" not in cols:
        conn.execute("ALTER TABLE memory_items ADD COLUMN recording_id TEXT")


def delete_expired(conn: Any, now_iso: str) -> int:
    cur = conn.execute(
        """
        DELETE FROM memory_items
        WHERE expires_at IS NOT NULL AND expires_at != '' AND expires_at <= ?
        """,
        (now_iso,),
    )
    return int(cur.rowcount or 0)


def count_recent_writes(
    conn: Any,
    *,
    account_id: str,
    writer: str,
    since: str,
    scope: str,
) -> int:
    pod_sql, pod_args = _rate_pod(scope)
    cur = conn.execute(
        f"""
        SELECT COUNT(*) AS n FROM memory_items
        WHERE account_id = ? AND created_by = ? AND created_at >= ? AND {pod_sql}
        """,
        (account_id, writer, since, *pod_args),
    )
    row = cur.fetchone()
    return int(row["n"] if row else 0)


def fetch_item(conn: Any, item_id: str, account_id: str) -> Any | None:
    cur = conn.execute(
        "SELECT * FROM memory_items WHERE id = ? AND account_id = ?",
        (item_id, account_id),
    )
    return cur.fetchone()


def fetch_by_hash(conn: Any, account_id: str, pod: str, content_hash: str) -> Any | None:
    cur = conn.execute(
        """
        SELECT * FROM memory_items
        WHERE account_id = ? AND pod = ? AND content_hash = ?
        """,
        (account_id, pod, content_hash),
    )
    return cur.fetchone()


def insert_item(
    conn: Any,
    *,
    item_id: str,
    account_id: str,
    pod: str,
    kind: str,
    title: str,
    body: str,
    job_id: str | None,
    company: str | None,
    tags_json: str | None,
    importance: int,
    pinned: int,
    content_hash: str,
    writer: str,
    created_track: str | None,
    created_at: str,
    updated_at: str,
    expires_at: str | None,
    since: str,
    scope: str,
    cap: int,
) -> Any | None:
    """Insert one row unless the hash exists or the writer is at ``cap``.

    ``ON CONFLICT (account_id, pod, content_hash) DO NOTHING`` is the dedupe.
    A filtered or conflicting insert returns None.
    """
    pod_sql, pod_args = _rate_pod(scope)
    cur = conn.execute(
        f"""
        INSERT INTO memory_items (
            id, account_id, pod, kind, title, body, job_id, company, tags_json, importance, pinned,
            content_hash, created_by, created_track, created_at, updated_at, expires_at,
            last_recalled_at, recall_count
        )
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0
        WHERE (
            SELECT COUNT(*) FROM memory_items
            WHERE account_id = ? AND created_by = ? AND created_at >= ? AND {pod_sql}
        ) < ?
        ON CONFLICT (account_id, pod, content_hash) DO NOTHING
        RETURNING *
        """,
        (
            item_id,
            account_id,
            pod,
            kind,
            title,
            body,
            job_id,
            company,
            tags_json,
            importance,
            pinned,
            content_hash,
            writer,
            created_track,
            created_at,
            updated_at,
            expires_at,
            account_id,
            writer,
            since,
            *pod_args,
            cap,
        ),
    )
    return cur.fetchone()


def touch_recalled(
    conn: Any,
    item_ids: Sequence[str],
    *,
    now: str,
    account_id: str,
) -> None:
    """One UPDATE per chunk. Each statement binds at most 90 parameters."""
    ids = list(item_ids)
    if not ids:
        return
    chunk_size = TOUCH_BIND_BUDGET - _TOUCH_FIXED_BINDS
    for start in range(0, len(ids), chunk_size):
        chunk = ids[start : start + chunk_size]
        marks = ",".join("?" for _ in chunk)
        conn.execute(
            f"""
            UPDATE memory_items
            SET last_recalled_at = ?, recall_count = recall_count + 1
            WHERE account_id = ? AND id IN ({marks})
            """,
            (now, account_id, *chunk),
        )


def list_items(
    conn: Any,
    *,
    account_id: str,
    pod: str | None,
    visible_pods: Sequence[str] | None,
    include_expired: bool,
    now: str,
    kind: str | None,
    job_id: str | None,
    company: str | None,
    query: str | None,
    limit: int,
) -> list[Any]:
    clauses = ["account_id = ?"]
    args: list[Any] = [account_id]
    if pod is not None:
        clauses.append("pod = ?")
        args.append(pod)
    else:
        pods = list(visible_pods or [])
        marks = ",".join("?" for _ in pods)
        clauses.append(f"pod IN ({marks})")
        args.extend(pods)
    if not include_expired:
        clauses.append(LIVE_CLAUSE)
        args.append(now)
    if kind is not None:
        clauses.append("kind = ?")
        args.append(kind)
    if job_id is not None:
        clauses.append("job_id = ?")
        args.append(job_id)
    if company is not None:
        clauses.append("lower(COALESCE(company, '')) = lower(?)")
        args.append(company)
    pattern = search_like_pattern(query)
    if pattern:
        clauses.append(_LIKE_FIELDS)
        args.extend((pattern, pattern, pattern))
    cur = conn.execute(
        f"""
        SELECT * FROM memory_items
        WHERE {' AND '.join(clauses)}
        ORDER BY pinned DESC, importance DESC, updated_at DESC
        LIMIT ?
        """,
        (*args, limit),
    )
    return list(cur.fetchall())


def forget_item(conn: Any, *, item_id: str, account_id: str, now: str) -> None:
    conn.execute(
        """
        UPDATE memory_items
        SET expires_at = ?, updated_at = ?
        WHERE id = ? AND account_id = ?
        """,
        (now, now, item_id, account_id),
    )


def update_item(
    conn: Any,
    *,
    title: str,
    body: str,
    pinned: int,
    expires_at: str | None,
    content_hash: str,
    updated_at: str,
    item_id: str,
    account_id: str,
) -> None:
    conn.execute(
        """
        UPDATE memory_items
        SET title = ?, body = ?, pinned = ?, expires_at = ?, content_hash = ?, updated_at = ?
        WHERE id = ? AND account_id = ?
        """,
        (title, body, pinned, expires_at, content_hash, updated_at, item_id, account_id),
    )


def delete_item(conn: Any, item_id: str, account_id: str) -> None:
    conn.execute(
        "DELETE FROM memory_items WHERE id = ? AND account_id = ?",
        (item_id, account_id),
    )


def move_item(
    conn: Any,
    *,
    pod: str,
    kind: str,
    title: str,
    body: str,
    content_hash: str,
    updated_at: str,
    item_id: str,
    account_id: str,
) -> None:
    conn.execute(
        """
        UPDATE memory_items
        SET pod = ?, kind = ?, title = ?, body = ?, content_hash = ?, updated_at = ?
        WHERE id = ? AND account_id = ?
        """,
        (pod, kind, title, body, content_hash, updated_at, item_id, account_id),
    )


def set_solidify(
    conn: Any,
    *,
    status: str,
    recording_id: str | None,
    updated_at: str,
    item_id: str,
    account_id: str,
) -> None:
    conn.execute(
        """
        UPDATE memory_items
        SET solidify_status = ?, recording_id = ?, updated_at = ?
        WHERE id = ? AND account_id = ?
        """,
        (status, recording_id, updated_at, item_id, account_id),
    )


def _column_names(conn: Any, table: str) -> set[str]:
    try:
        return sql_column_names(conn, table)
    except Exception:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _rate_pod(scope: str) -> tuple[str, tuple[Any, ...]]:
    if scope == POD_KIND_COMMON:
        return "pod = ?", (POD_COMMON,)
    if scope == POD_KIND_TRACK:
        return "pod LIKE 'track:%'", ()
    if scope == POD_KIND_WORKER:
        return "pod LIKE 'worker:%'", ()
    raise ValueError(f"unknown memory scope: {scope}")
