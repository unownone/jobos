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
from app.storage.message_queue import InlineQueue, MessageQueue, PayloadTooLarge, SentMessage
from app.storage.port import Database, QueryCounter, Result, Stmt
from app.storage.work_queue import (
    Conflict,
    NotFound,
    PushResult,
    QueueItem,
    SqlWorkQueue,
    TooManyKinds,
    WorkQueue,
)

__all__ = [
    "CheckViolation",
    "Conflict",
    "Database",
    "ForeignKeyViolation",
    "InlineQueue",
    "MessageQueue",
    "NotFound",
    "ParameterLimitError",
    "PayloadTooLarge",
    "PushResult",
    "QueryCounter",
    "QueueItem",
    "Result",
    "SentMessage",
    "SqlWorkQueue",
    "Stmt",
    "StorageError",
    "TooManyKinds",
    "TransientError",
    "UniqueViolation",
    "WorkQueue",
    "chunked_in",
    "d1_dialect",
    "postgres_dialect",
    "sqlite_dialect",
]
