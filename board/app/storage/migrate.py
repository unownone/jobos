"""Apply ``board/migrations/sqlite`` to a sqlite connection.

Each filename is recorded in ``schema_migrations`` in the same transaction as
that file. Application startup does not call this module. The live Hub still
builds its schema through ``ensure_*`` until a later cutover.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sqlite_migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "migrations" / "sqlite"


def apply_sqlite(conn: Any, directory: Path | None = None) -> list[str]:
    """Apply pending ``*.sql`` files in filename order.

    Returns the versions applied by this call. Versions already stored in
    ``schema_migrations`` are skipped. ``directory`` defaults to
    ``board/migrations/sqlite``.
    """
    root = Path(directory) if directory is not None else sqlite_migrations_dir()
    if not root.is_dir():
        raise FileNotFoundError(f"sqlite migrations directory not found: {root}")
    if getattr(conn, "in_transaction", False):
        raise RuntimeError("apply_sqlite requires a connection with no open transaction")
    _ensure_schema_migrations(conn)
    done = _recorded_versions(conn)
    applied: list[str] = []
    stamp = _utc_now()
    for path in _sql_files(root):
        version = path.name
        if version in done:
            continue
        _apply_file(conn, path.read_text(encoding="utf-8"), version, stamp)
        applied.append(version)
    return applied


def split_sql(script: str) -> list[str]:
    """Split a script on semicolons. Line and block comments are ignored."""
    cleaned = _strip_comments(script)
    parts: list[str] = []
    buf: list[str] = []
    in_single = False
    i = 0
    while i < len(cleaned):
        ch = cleaned[i]
        if ch == "'" and not in_single:
            in_single = True
            buf.append(ch)
        elif in_single and ch == "'":
            if i + 1 < len(cleaned) and cleaned[i + 1] == "'":
                buf.append("''")
                i += 2
                continue
            in_single = False
            buf.append(ch)
        elif ch == ";" and not in_single:
            stmt = "".join(buf).strip()
            if stmt:
                parts.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _ensure_schema_migrations(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    _commit(conn)


def _recorded_versions(conn: Any) -> set[str]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {_version_cell(row) for row in rows}


def _version_cell(row: Any) -> str:
    if isinstance(row, dict):
        return str(row["version"])
    keys = getattr(row, "keys", None)
    if callable(keys):
        return str(row["version"])
    return str(row[0])


def _sql_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.iterdir() if path.is_file() and path.suffix == ".sql")


def _apply_file(conn: Any, script: str, version: str, stamp: str) -> None:
    """Run one file and its schema_migrations row in a single transaction."""
    conn.execute("BEGIN")
    try:
        for statement in split_sql(script):
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, stamp),
        )
        _commit(conn)
    except Exception:
        _rollback(conn)
        raise


def _commit(conn: Any) -> None:
    commit = getattr(conn, "commit", None)
    if callable(commit):
        commit()


def _rollback(conn: Any) -> None:
    rollback = getattr(conn, "rollback", None)
    if callable(rollback):
        rollback()
        return
    conn.execute("ROLLBACK")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _strip_comments(script: str) -> str:
    out: list[str] = []
    i = 0
    n = len(script)
    in_single = False
    while i < n:
        ch = script[i]
        nxt = script[i + 1] if i + 1 < n else ""
        if in_single:
            out.append(ch)
            if ch == "'":
                if nxt == "'":
                    out.append(nxt)
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if ch == "'":
            in_single = True
            out.append(ch)
            i += 1
            continue
        if ch == "-" and nxt == "-":
            i += 2
            while i < n and script[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (script[i] == "*" and script[i + 1] == "/"):
                i += 1
            i = min(i + 2, n)
            continue
        out.append(ch)
        i += 1
    return "".join(out)
