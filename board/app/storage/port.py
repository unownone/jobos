"""Synchronous database port. No interactive transactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from app.storage.dialect import Dialect


class QueryCounter:
    def __init__(self) -> None:
        self.count = 0

    def reset(self) -> None:
        self.count = 0

    def add(self, amount: int = 1) -> None:
        self.count += amount


@dataclass(frozen=True)
class Stmt:
    sql: str
    params: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", tuple(self.params))


@dataclass(frozen=True)
class Result:
    rowcount: int
    last_id: int | None = None
    rows: tuple[Mapping[str, Any], ...] = ()


class Database(Protocol):
    dialect: Dialect
    queries: QueryCounter

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> Mapping[str, Any] | None:
        """Return the first row, or None."""

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[Mapping[str, Any]]:
        """Return every row from a read."""

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Result:
        """Run one statement. RETURNING rows are on Result.rows."""

    def batch(self, stmts: Sequence[Stmt]) -> list[Result]:
        """Run every statement in one atomic batch, or none of them."""
