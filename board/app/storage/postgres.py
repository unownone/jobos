"""Postgres adapter for the database port.

Repository SQL keeps ``?`` placeholders. This module rewrites them to psycopg
``%s`` and leaves placeholders the Postgres dialect already emitted. A single
statement whose connection drops is tried once more on a new session. A batch
stays one transaction and is not replayed.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, NoReturn, Sequence

import psycopg
from psycopg.rows import dict_row

from app.storage.dialect import postgres_dialect
from app.storage.errors import (
    CheckViolation,
    ForeignKeyViolation,
    StorageError,
    TransientError,
    UniqueViolation,
)
from app.storage.port import QueryCounter, Result, Stmt

_UNIQUE = "23505"
_CHECK = "23514"
_FOREIGN_KEY = "23503"
# SQLSTATEs worth retrying as TransientError. 08007 (outcome unknown) is absent
# so a lost commit is not reported as safe to replay.
_TRANSIENT = frozenset(
    {
        "40001",  # serialization_failure
        "40P01",  # deadlock_detected
        "55P03",  # lock_not_available
        "53300",  # too_many_connections
        "57P03",  # cannot_connect_now
        "08000",  # connection_exception
        "08001",  # sqlclient_unable_to_establish_sqlconnection
        "08003",  # connection_does_not_exist
        "08004",  # sqlserver_rejected_establishment_of_sqlconnection
        "08006",  # connection_failure
        "57P01",  # admin_shutdown
        "57P02",  # crash_shutdown
    }
)
_DROPPED = frozenset(
    {
        "08000",
        "08001",
        "08003",
        "08004",
        "08006",
        "57P01",
        "57P02",
        "57P03",
    }
)
_DOLLAR = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
_LOST_WORDS = ("closed", "lost", "broken", "reset", "terminated", "unexpected")


def translate_placeholders(sql: str) -> str:
    """Turn port ``?`` binds into ``%s`` and escape literal percents for psycopg.

    ``%s``, ``%b``, ``%t``, ``%%``, and ``%(name)s`` outside quotes are already
    psycopg placeholders (the Postgres dialect emits ``%s``) and stay as they are.
    Question marks inside strings, escape strings, comments, and dollar quotes
    stay literal. A backslash in an ``E'...'`` literal escapes the next character.
    """
    out: list[str] = []
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if char == "-" and index + 1 < length and sql[index + 1] == "-":
            end = sql.find("\n", index)
            end = length if end < 0 else end + 1
            out.append(sql[index:end].replace("%", "%%"))
            index = end
            continue
        if char == "/" and index + 1 < length and sql[index + 1] == "*":
            end = sql.find("*/", index + 2)
            end = length if end < 0 else end + 2
            out.append(sql[index:end].replace("%", "%%"))
            index = end
            continue
        if char == "'":
            if _is_escape_string(sql, index):
                end = _escape_string_end(sql, index)
            else:
                end = _quoted_end(sql, index, "'")
            out.append(sql[index:end].replace("%", "%%"))
            index = end
            continue
        if char == '"':
            end = _quoted_end(sql, index, '"')
            out.append(sql[index:end].replace("%", "%%"))
            index = end
            continue
        if char == "$":
            tag = _dollar_at(sql, index)
            if tag is not None:
                close = sql.find(tag, index + len(tag))
                end = length if close < 0 else close + len(tag)
                out.append(sql[index:end].replace("%", "%%"))
                index = end
                continue
        if char == "?":
            out.append("%s")
            index += 1
            continue
        if char == "%":
            token = _placeholder_at(sql, index)
            if token is not None:
                out.append(token)
                index += len(token)
                continue
            out.append("%%")
            index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def map_postgres_error(exc: BaseException) -> StorageError | None:
    """Map a psycopg error's SQLSTATE onto the port's normalized errors."""
    if not isinstance(exc, psycopg.Error):
        return None
    code = exc.sqlstate
    if code == _UNIQUE:
        return UniqueViolation(str(exc))
    if code == _CHECK:
        return CheckViolation(str(exc))
    if code == _FOREIGN_KEY:
        return ForeignKeyViolation(str(exc))
    if code in _TRANSIENT or _dropped(exc):
        return TransientError(str(exc))
    return None


class PostgresDatabase:
    def __init__(self, dsn: str) -> None:
        self.dialect = postgres_dialect()
        self.queries = QueryCounter()
        self._dsn = dsn
        self._conn: psycopg.Connection[Any] | None = None

    def close(self) -> None:
        self._reset()

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> Mapping[str, Any] | None:
        result = self._run(sql, params)
        if not result.rows:
            return None
        return result.rows[0]

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[Mapping[str, Any]]:
        return list(self._run(sql, params).rows)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Result:
        return self._run(sql, params)

    def batch(self, stmts: Sequence[Stmt]) -> list[Result]:
        """Run every statement in one transaction. A failure rolls the whole batch back."""
        prepared = [Stmt(stmt.sql, stmt.params) for stmt in stmts]
        if not prepared:
            return []
        conn = self._live()
        results: list[Result] = []
        try:
            with conn.transaction():
                for stmt in prepared:
                    results.append(self._query(conn, stmt.sql, stmt.params))
            return results
        except Exception as exc:
            self._raise(exc)

    def _run(self, sql: str, params: Sequence[Any]) -> Result:
        """One autocommit-style transaction, retried once if the session dropped."""
        saved: BaseException | None = None
        for attempt in (1, 2):
            conn = self._live()
            executed = False
            try:
                with conn.transaction():
                    result = self._query(conn, sql, params)
                    executed = True
                return result
            except Exception as exc:
                saved = exc
                # A failure after the statement ran may already be committed.
                # Replaying it could apply the write twice, so only a drop
                # before execution opens a new session.
                if (
                    attempt == 1
                    and not executed
                    and (_dropped(exc) or bool(getattr(conn, "closed", False)))
                ):
                    self._reset()
                    continue
                self._raise(exc)
        assert saved is not None
        self._raise(saved)

    def _query(self, conn: Any, sql: str, params: Sequence[Any]) -> Result:
        try:
            cursor = conn.execute(translate_placeholders(sql), tuple(params))
            rows: tuple[Mapping[str, Any], ...] = ()
            if cursor.description is not None:
                rows = tuple(dict(row) for row in cursor.fetchall())
            rowcount = cursor.rowcount if cursor.rowcount is not None else -1
            return Result(rowcount=rowcount, last_id=_last_id(rows), rows=rows)
        finally:
            self.queries.add(1)

    def _live(self) -> Any:
        conn = self._conn
        if conn is not None and not bool(getattr(conn, "closed", True)):
            return conn
        self._reset()
        try:
            self._conn = psycopg.connect(
                self._dsn,
                row_factory=dict_row,
                autocommit=False,
                connect_timeout=10,
            )
        except Exception as exc:
            # One attempt. A database that is still starting (57P03) is transient,
            # and a failed connect must not replay a batch or loop.
            self._raise(exc)
        return self._conn

    def _reset(self) -> None:
        conn = self._conn
        self._conn = None
        if conn is None:
            return
        try:
            conn.close()
        except Exception:
            return

    def _raise(self, exc: BaseException) -> NoReturn:
        if isinstance(exc, StorageError):
            raise exc
        mapped = map_postgres_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise exc


def _last_id(rows: tuple[Mapping[str, Any], ...]) -> int | None:
    if not rows or "id" not in rows[-1]:
        return None
    value = rows[-1]["id"]
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _dropped(exc: BaseException) -> bool:
    if isinstance(exc, psycopg.Error) and exc.sqlstate in _DROPPED:
        return True
    if not isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)):
        return False
    text = str(exc).lower()
    return "connection" in text and any(word in text for word in _LOST_WORDS)


def _is_escape_string(sql: str, quote_index: int) -> bool:
    """True when the quote opens an ``E'...'`` literal, not an identifier ending in E."""
    if quote_index < 1 or sql[quote_index] != "'":
        return False
    if sql[quote_index - 1] not in {"E", "e"}:
        return False
    if quote_index == 1:
        return True
    before = sql[quote_index - 2]
    return not (before.isalnum() or before == "_")


def _escape_string_end(sql: str, start: int) -> int:
    """Return the index just after an ``E'...'`` literal. ``start`` is the opening quote."""
    index = start + 1
    length = len(sql)
    while index < length:
        char = sql[index]
        if char == "\\":
            if index + 1 >= length:
                return length
            index += 2
            continue
        if char == "'":
            if index + 1 < length and sql[index + 1] == "'":
                index += 2
                continue
            return index + 1
        index += 1
    return length


def _quoted_end(sql: str, start: int, quote: str) -> int:
    index = start + 1
    length = len(sql)
    while index < length:
        if sql[index] == quote:
            if index + 1 < length and sql[index + 1] == quote:
                index += 2
                continue
            return index + 1
        index += 1
    return length


def _dollar_at(sql: str, start: int) -> str | None:
    match = _DOLLAR.match(sql, start)
    if match is None:
        return None
    return match.group(0)


def _placeholder_at(sql: str, start: int) -> str | None:
    if start + 1 >= len(sql):
        return None
    nxt = sql[start + 1]
    if nxt in "%sbt":
        return sql[start : start + 2]
    if nxt != "(":
        return None
    close = sql.find(")", start + 2)
    if close < 0 or close + 1 >= len(sql) or sql[close + 1] not in "sbt":
        return None
    return sql[start : close + 2]
