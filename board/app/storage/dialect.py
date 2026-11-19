"""Dialect differences. Portable SQL stays in `?` form; this is the only switch."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _require_ident(column: str) -> str:
    if not isinstance(column, str) or _IDENT.fullmatch(column) is None:
        raise ValueError(f"unsafe column name: {column!r}")
    return column


@dataclass(frozen=True)
class Dialect:
    """Non-portable SQL knobs. ``skip_locked`` is unused until the Postgres claim path."""

    name: str
    placeholder: str
    max_params: int
    skip_locked: str | None = None

    def icontains(self, column: str) -> str:
        """Case-insensitive substring test. Never emits LIKE."""
        ident = _require_ident(column)
        placeholder = self.placeholder
        if self.name in {"sqlite", "d1"}:
            return f"instr(lower({ident}), lower({placeholder})) > 0"
        if self.name == "postgres":
            return f"strpos(lower({ident}), lower({placeholder})) > 0"
        raise ValueError(f"unsupported dialect {self.name}")


def sqlite_dialect() -> Dialect:
    return Dialect(name="sqlite", placeholder="?", max_params=100, skip_locked=None)


def d1_dialect() -> Dialect:
    return Dialect(name="d1", placeholder="?", max_params=100, skip_locked=None)


def postgres_dialect() -> Dialect:
    # psycopg binds with %s. Repository SQL still uses ?; the Postgres adapter rewrites it.
    return Dialect(name="postgres", placeholder="%s", max_params=65535, skip_locked="SKIP LOCKED")


def chunked_in(
    dialect: Dialect,
    column: str,
    values: Sequence[Any],
    *,
    reserved: int = 10,
) -> list[tuple[str, tuple[Any, ...]]]:
    """Split an IN-list so each chunk leaves ``reserved`` parameters for the rest of the statement."""
    ident = _require_ident(column)
    if not values:
        return []
    if dialect.max_params < 1:
        raise ValueError("max_params must be positive")
    if 0 <= reserved < dialect.max_params:
        size = dialect.max_params - reserved
    else:
        size = dialect.max_params
    chunks: list[tuple[str, tuple[Any, ...]]] = []
    for start in range(0, len(values), size):
        part = tuple(values[start : start + size])
        placeholders = ",".join([dialect.placeholder] * len(part))
        chunks.append((f"{ident} IN ({placeholders})", part))
    return chunks
