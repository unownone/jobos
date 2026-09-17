"""PostgreSQL adapter with a sqlite-like execute surface.

Hub durable state lives in Postgres. Tests isolate via per-path schemas.
Placeholders: qmark `?` and named `:id` (sqlite style) are translated.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

_NAMED = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")
_SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_ON_CONFLICT = re.compile(r"ON CONFLICT\s*\(([^)]+)\)", re.I)
_LIKE = re.compile(r"\bLIKE\b", re.I)


class SqlCursor:
    def __init__(self, rows: list[Any], *, lastrowid: int | None, rowcount: int) -> None:
        self._rows = rows
        self._i = 0
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self) -> Any:
        if self._i >= len(self._rows):
            return None
        row = self._rows[self._i]
        self._i += 1
        return row

    def fetchall(self) -> list[Any]:
        rest = self._rows[self._i :]
        self._i = len(self._rows)
        return rest

    def __iter__(self) -> SqlCursor:
        return self

    def __next__(self) -> Any:
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row


class SqlConnection:
    """Thin psycopg wrapper so existing `?` / `:name` SQL keeps working."""

    def __init__(self, raw: psycopg.Connection, *, schema: str) -> None:
        self._raw = raw
        self.schema = schema
        self._lock = threading.Lock()

    def execute(self, sql: str, params: Any = ()) -> SqlCursor:
        text = sql.strip()
        upper = " ".join(text.upper().split())
        if upper.startswith("PRAGMA "):
            return self._pragma(text)
        if upper in {"BEGIN", "BEGIN IMMEDIATE", "BEGIN EXCLUSIVE"}:
            # psycopg starts a transaction on the first statement after commit.
            return SqlCursor([], lastrowid=None, rowcount=-1)
        if upper == "VACUUM":
            return SqlCursor([], lastrowid=None, rowcount=-1)

        returning_id = False
        if (
            upper.startswith("INSERT INTO EVENTS")
            or upper.startswith("INSERT INTO TOKEN_BURN")
        ) and "RETURNING" not in upper:
            text = text.rstrip().rstrip(";") + " RETURNING id"
            returning_id = True

        pg_sql, pg_params = adapt_sql(text, params)
        with self._lock:
            cur = self._raw.execute(pg_sql, pg_params)
            rows: list[Any] = []
            lastrowid = None
            rowcount = cur.rowcount if cur.rowcount is not None else -1
            if cur.description:
                rows = list(cur.fetchall())
                if returning_id and rows:
                    lastrowid = rows[0]["id"]
                    rows = []
            return SqlCursor(rows, lastrowid=lastrowid, rowcount=rowcount)

    def executescript(self, script: str) -> None:
        for stmt in split_sql(script):
            self.execute(stmt)

    def commit(self) -> None:
        with self._lock:
            self._raw.commit()

    def rollback(self) -> None:
        with self._lock:
            self._raw.rollback()

    def close(self) -> None:
        with self._lock:
            self._raw.close()

    def _pragma(self, sql: str) -> SqlCursor:
        match = re.search(r"PRAGMA\s+table_info\((\w+)\)", sql, re.I)
        if not match:
            return SqlCursor([], lastrowid=None, rowcount=-1)
        table = match.group(1)
        names = column_names(self, table)
        # sqlite PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
        rows = [{"name": n, 1: n} for n in sorted(names)]
        return SqlCursor(rows, lastrowid=None, rowcount=len(rows))


def adapt_sql(sql: str, params: Any) -> tuple[str, Any]:
    if params is None:
        params = ()
    # psycopg treats % as placeholders. Literal LIKE wildcards must be doubled first.
    sql = sql.replace("%", "%%")
    if isinstance(params, dict):
        names: list[str] = []

        def _named(match: re.Match[str]) -> str:
            names.append(match.group(1))
            return "%s"

        pg_sql = _NAMED.sub(_named, sql)
        pg_sql = _pg_rewrite(pg_sql)
        return pg_sql, tuple(params[name] for name in names)
    if not isinstance(params, (list, tuple)):
        params = (params,)
    pg_sql = sql.replace("?", "%s")
    pg_sql = _pg_rewrite(pg_sql)
    return pg_sql, tuple(params)


def _pg_rewrite(sql: str) -> str:
    sql = _ON_CONFLICT.sub(lambda m: f"ON CONFLICT ({m.group(1)})", sql)
    if "CREATE TABLE" not in sql.upper() and "CREATE INDEX" not in sql.upper():
        sql = _LIKE.sub("ILIKE", sql)
    return sql


def split_sql(script: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    in_single = False
    i = 0
    while i < len(script):
        ch = script[i]
        if ch == "'" and not in_single:
            in_single = True
            buf.append(ch)
        elif ch == "'" and in_single:
            if i + 1 < len(script) and script[i + 1] == "'":
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


def schema_name_for_path(db_path: Path) -> str:
    digest = hashlib.sha256(str(db_path.resolve()).encode("utf-8")).hexdigest()[:20]
    return "s" + digest


def quote_ident(name: str) -> str:
    if not _SAFE_IDENT.match(name):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name


def column_names(conn: SqlConnection, table: str) -> set[str]:
    ident = quote_ident(table)
    cur = conn.execute(
        """
        SELECT column_name AS name
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = ?
        """,
        (ident,),
    )
    return {str(row["name"]) for row in cur.fetchall()}


def connect_url(database_url: str, *, schema: str | None = None) -> SqlConnection:
    if not database_url:
        raise RuntimeError("DATABASE_URL is required (PostgreSQL). SQLite volumes are gone.")
    raw = psycopg.connect(database_url, row_factory=dict_row, autocommit=True)
    schema_name = schema or "public"
    ident = quote_ident(schema_name)
    raw.execute(f"CREATE SCHEMA IF NOT EXISTS {ident}")
    raw.execute(f"SET search_path TO {ident}")
    raw.autocommit = False
    return SqlConnection(raw, schema=schema_name)


def resolve_database_url(explicit: str | None = None) -> str:
    return (explicit or os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL") or "").strip()


def schema_for_db_path(db_path: Path) -> str:
    if os.environ.get("JOBOS_PG_SCHEMA"):
        return os.environ["JOBOS_PG_SCHEMA"].strip() or "public"
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return schema_name_for_path(db_path)
    return "public"
