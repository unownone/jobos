"""SQLite adapter stub. Behavior is filled in after the contract tests fail."""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping, Sequence

from app.storage.dialect import sqlite_dialect
from app.storage.errors import StorageError
from app.storage.port import QueryCounter, Result, Stmt


class SqliteDatabase:
    def __init__(self, path: str = ":memory:", *, strict_d1: bool = False) -> None:
        del path, strict_d1
        self.dialect = sqlite_dialect()
        self.queries = QueryCounter()

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> Mapping[str, Any] | None:
        del sql, params
        return None

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[Mapping[str, Any]]:
        del sql, params
        return []

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Result:
        del sql, params
        return Result(rowcount=0)

    def batch(self, stmts: Sequence[Stmt]) -> list[Result]:
        del stmts
        return []


def map_sqlite_error(exc: sqlite3.Error) -> StorageError | None:
    del exc
    return None
