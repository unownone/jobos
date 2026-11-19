"""Storage port. Adapters implement Database."""

from app.storage.dialect import chunked_in, d1_dialect, postgres_dialect, sqlite_dialect
from app.storage.errors import (
    CheckViolation,
    ForeignKeyViolation,
    ParameterLimitError,
    StorageError,
    TransientError,
    UniqueViolation,
)
from app.storage.port import Database, QueryCounter, Result, Stmt

__all__ = [
    "CheckViolation",
    "Database",
    "ForeignKeyViolation",
    "ParameterLimitError",
    "QueryCounter",
    "Result",
    "Stmt",
    "StorageError",
    "TransientError",
    "UniqueViolation",
    "chunked_in",
    "d1_dialect",
    "postgres_dialect",
    "sqlite_dialect",
]
