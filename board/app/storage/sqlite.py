"""SQLite adapter for tests, local runs, and small installs.

Strict D1 mode rejects statements with more than ``dialect.max_params`` bound
parameters (100). ``skip_locked`` is not applied.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.storage.dialect import sqlite_dialect
from app.storage.errors import (
    CheckViolation,
    ForeignKeyViolation,
    ParameterLimitError,
    StorageError,
    TransientError,
    UniqueViolation,
)
from app.storage.port import QueryCounter, Result, Stmt


def map_sqlite_error(exc: sqlite3.Error) -> StorageError | None:
    message = str(exc).lower()
    if isinstance(exc, sqlite3.IntegrityError):
        if "unique" in message:
            return UniqueViolation(str(exc))
        if "check" in message:
            return CheckViolation(str(exc))
        if "foreign key" in message:
            return ForeignKeyViolation(str(exc))
    if isinstance(exc, sqlite3.OperationalError) and ("locked" in message or "busy" in message):
        return TransientError(str(exc))
    return None


class SqliteDatabase:
    def __init__(self, path: str | Path = ":memory:", *, strict_d1: bool = False) -> None:
        self.dialect = sqlite_dialect()
        self.strict_d1 = strict_d1
        self.queries = QueryCounter()
        self._conn = sqlite3.connect(str(path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self._conn.close()

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> Mapping[str, Any] | None:
        result = self._execute(sql, params)
        if not result.rows:
            return None
        return result.rows[0]

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[Mapping[str, Any]]:
        return list(self._execute(sql, params).rows)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Result:
        return self._execute(sql, params)

    def batch(self, stmts: Sequence[Stmt]) -> list[Result]:
        """Run every statement in one transaction. A failure rolls the whole batch back."""
        prepared = [Stmt(stmt.sql, stmt.params) for stmt in stmts]
        for stmt in prepared:
            self._guard(stmt.params)
        if not prepared:
            return []
        self._conn.execute("BEGIN")
        results: list[Result] = []
        try:
            for stmt in prepared:
                results.append(self._execute(stmt.sql, stmt.params, guarded=True))
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")
        return results

    def _guard(self, params: Sequence[Any]) -> None:
        count = len(tuple(params))
        if self.strict_d1 and count > self.dialect.max_params:
            raise ParameterLimitError(count, self.dialect.max_params)

    def _execute(
        self,
        sql: str,
        params: Sequence[Any] = (),
        *,
        guarded: bool = False,
    ) -> Result:
        bound = tuple(params)
        if not guarded:
            self._guard(bound)
        try:
            cursor = self._conn.execute(sql, bound)
            rows: tuple[Mapping[str, Any], ...] = ()
            if cursor.description is not None:
                rows = tuple(dict(row) for row in cursor.fetchall())
            rowcount = cursor.rowcount if cursor.rowcount is not None else -1
            return Result(rowcount=rowcount, last_id=cursor.lastrowid, rows=rows)
        except sqlite3.Error as exc:
            mapped = map_sqlite_error(exc)
            if mapped is not None:
                raise mapped from exc
            raise
        finally:
            self.queries.add(1)
