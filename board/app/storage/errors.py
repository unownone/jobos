"""Normalized database errors shared by every adapter."""

from __future__ import annotations


class StorageError(Exception):
    """Base for errors the port normalizes across engines."""


class UniqueViolation(StorageError):
    """A UNIQUE constraint rejected the write."""


class CheckViolation(StorageError):
    """A CHECK constraint rejected the write."""


class ForeignKeyViolation(StorageError):
    """A FOREIGN KEY constraint rejected the write."""


class TransientError(StorageError):
    """The engine was busy or the connection dropped. Safe to retry the batch."""


class ParameterLimitError(StorageError):
    """A statement binds more parameters than the dialect allows."""

    def __init__(self, count: int, limit: int) -> None:
        super().__init__(f"statement binds {count} parameters; limit is {limit}")
        self.count = count
        self.limit = limit
