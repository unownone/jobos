"""SQLite batch() must roll back when COMMIT fails after the writes succeed.

The first explicit COMMIT raises sqlite3.OperationalError after the INSERT has
returned. A later batch commits only its own row.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Sequence

import pytest

from app.storage.errors import TransientError
from app.storage.port import Stmt
from app.storage.sqlite import SqliteDatabase

STAMP = "2020-01-01T00:00:00Z"


class _FailFirstCommit:
    """Real connection whose first COMMIT raises; later commits run as usual.

    The INSERT is executed on the underlying connection before that raise, so
    the error is not a statement-level lock.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self.commit_attempts = 0
        self.insert_rowcount: int | None = None
        self.visible_names_at_failed_commit: list[str] = []
        self.in_transaction_at_failed_commit = False
        self.verbs: list[str] = []

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        verb = sql.strip().split(None, 1)[0].upper()
        if verb == "COMMIT":
            self.commit_attempts += 1
            if self.commit_attempts == 1:
                rows = self._conn.execute("SELECT name FROM items ORDER BY name").fetchall()
                self.visible_names_at_failed_commit = [row["name"] for row in rows]
                self.in_transaction_at_failed_commit = self._conn.in_transaction
                raise sqlite3.OperationalError("database is locked")
        cursor = self._conn.execute(sql, params)
        self.verbs.append(verb)
        if verb == "INSERT" and self.commit_attempts == 0:
            self.insert_rowcount = cursor.rowcount
        return cursor

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _schema(db: SqliteDatabase) -> None:
    db.execute(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            n INTEGER NOT NULL CHECK (n >= 0),
            on_flag INTEGER NOT NULL,
            ts TEXT NOT NULL
        )
        """
    )


def _same_connection_names(db: SqliteDatabase) -> list[str]:
    rows = db.fetch_all("SELECT name FROM items ORDER BY name")
    return [row["name"] for row in rows]


def _committed_names(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [row[0] for row in conn.execute("SELECT name FROM items ORDER BY name")]
    finally:
        conn.close()


def test_batch_rolls_back_when_commit_fails(tmp_path) -> None:
    db_path = tmp_path / "batch_commit_busy.db"
    db = SqliteDatabase(db_path)
    _schema(db)
    gate = _FailFirstCommit(db._conn)
    db._conn = gate

    with pytest.raises(TransientError, match="locked|busy") as raised:
        db.batch(
            [
                Stmt(
                    "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
                    ("Acme", 1, 1, STAMP),
                ),
            ]
        )

    assert isinstance(raised.value.__cause__, sqlite3.OperationalError)
    assert gate.commit_attempts == 1
    assert gate.insert_rowcount == 1
    assert gate.visible_names_at_failed_commit == ["Acme"]
    assert gate.in_transaction_at_failed_commit is True
    assert gate.verbs == ["BEGIN", "INSERT", "ROLLBACK"]
    assert db._conn.in_transaction is False
    assert _same_connection_names(db) == []
    assert _committed_names(db_path) == []

    db.batch(
        [
            Stmt(
                "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
                ("Other", 2, 0, STAMP),
            ),
        ]
    )
    assert gate.commit_attempts == 2
    assert "COMMIT" in gate.verbs
    assert db._conn.in_transaction is False
    assert _same_connection_names(db) == ["Other"]
    assert _committed_names(db_path) == ["Other"]
