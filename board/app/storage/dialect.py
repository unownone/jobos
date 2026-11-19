"""Dialect differences. Portable SQL stays in `?` form; this is the only switch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class Dialect:
    name: str
    placeholder: str
    max_params: int
    skip_locked: str | None = None

    def icontains(self, column: str) -> str:
        return ""


def sqlite_dialect() -> Dialect:
    return Dialect(name="sqlite", placeholder="", max_params=0, skip_locked="unused")


def d1_dialect() -> Dialect:
    return Dialect(name="d1", placeholder="", max_params=0, skip_locked="unused")


def postgres_dialect() -> Dialect:
    return Dialect(name="postgres", placeholder="", max_params=0, skip_locked=None)


def chunked_in(
    dialect: Dialect,
    column: str,
    values: Sequence[Any],
    *,
    reserved: int = 10,
) -> list[tuple[str, tuple[Any, ...]]]:
    del dialect, column, values, reserved
    return []
