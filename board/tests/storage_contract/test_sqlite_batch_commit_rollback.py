"""SQLite batch() must roll back when COMMIT fails (e.g. SQLITE_BUSY)."""

from __future__ import annotations

import sqlite3

import pytest

from app.storage.errors import TransientError
from app.storage.port import Stmt
from app.storage.sqlite import SqliteDatabase

STAMP = "2020-01-01T00:00:00Z"


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


def test_batch_rolls_back_when_commit_fails(tmp_path) -> None:
    db_path = tmp_path / "batch_commit_busy.db"
    db = SqliteDatabase(db_path)
    _schema(db)

    locker = sqlite3.connect(db_path, isolation_level=None)
    try:
        locker.execute("BEGIN IMMEDIATE")
        with pytest.raises((sqlite3.OperationalError, TransientError)):
            db.batch(
                [
                    Stmt(
                        "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
                        ("Acme", 1, 1, STAMP),
                    ),
                ]
            )
    finally:
        locker.execute("ROLLBACK")
        locker.close()

    assert db._conn.in_transaction is False
    assert db.fetch_one("SELECT COUNT(*) AS c FROM items")["c"] == 0

    db.batch(
        [
            Stmt(
                "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
                ("Other", 2, 0, STAMP),
            ),
        ]
    )
    assert db.fetch_one("SELECT COUNT(*) AS c FROM items")["c"] == 1