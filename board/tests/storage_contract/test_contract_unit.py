"""Database port contract against the SQLite adapter. No Postgres."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from app.storage.dialect import chunked_in, d1_dialect, postgres_dialect, sqlite_dialect
from app.storage.errors import (
    CheckViolation,
    ForeignKeyViolation,
    ParameterLimitError,
    TransientError,
    UniqueViolation,
)
from app.storage.port import Stmt
from app.storage.sqlite import SqliteDatabase, map_sqlite_error

STAMP = "2020-01-01T00:00:00Z"


def fresh(*, strict_d1: bool = False) -> SqliteDatabase:
    db = SqliteDatabase(":memory:", strict_d1=strict_d1)
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
    db.execute(
        """
        CREATE TABLE children (
            id INTEGER PRIMARY KEY,
            item_id INTEGER NOT NULL REFERENCES items(id)
        )
        """
    )
    db.queries.reset()
    return db


def test_dialects_expose_placeholder_limits_and_icontains() -> None:
    sqlite = sqlite_dialect()
    d1 = d1_dialect()
    postgres = postgres_dialect()
    assert sqlite.placeholder == "?"
    assert sqlite.max_params == 100
    assert sqlite.skip_locked is None
    assert d1.placeholder == "?"
    assert d1.max_params == 100
    assert d1.skip_locked is None
    assert postgres.placeholder == "%s"
    assert postgres.skip_locked == "SKIP LOCKED"
    assert sqlite.icontains("title") == "instr(lower(title), lower(?)) > 0"
    assert d1.icontains("title") == "instr(lower(title), lower(?)) > 0"
    assert postgres.icontains("title") == "strpos(lower(title), lower(%s)) > 0"
    for fragment in (sqlite.icontains("title"), postgres.icontains("title")):
        assert "like" not in fragment.lower()


def test_icontains_rejects_untrusted_column_names() -> None:
    with pytest.raises(ValueError):
        sqlite_dialect().icontains("name LIKE")
    with pytest.raises(ValueError):
        sqlite_dialect().icontains("name;drop")


def test_chunked_in_splits_at_max_params_minus_reserved() -> None:
    values = list(range(250))
    chunks = chunked_in(sqlite_dialect(), "job_id", values)
    assert [len(params) for _, params in chunks] == [90, 90, 70]
    assert chunks[0][0] == "job_id IN (" + ",".join(["?"] * 90) + ")"
    assert [value for _, params in chunks for value in params] == values
    assert chunked_in(sqlite_dialect(), "job_id", []) == []
    postgres = chunked_in(postgres_dialect(), "job_id", [1, 2])
    assert postgres == [("job_id IN (%s,%s)", (1, 2))]


def test_query_counter_counts_each_statement_and_resets() -> None:
    db = fresh()
    assert db.queries.count == 0
    db.fetch_one("SELECT 1 AS n")
    db.fetch_all("SELECT 1 AS n")
    db.execute("SELECT 1 AS n")
    assert db.queries.count == 3
    db.batch([Stmt("SELECT 1 AS n"), Stmt("SELECT 2 AS n")])
    assert db.queries.count == 5
    db.queries.reset()
    assert db.queries.count == 0


def test_crud_returning_update_and_delete() -> None:
    db = fresh()
    inserted = db.execute(
        "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?) RETURNING id, name",
        ("Acme", 1, 1, STAMP),
    )
    assert inserted.rowcount == 1
    item_id = inserted.rows[0]["id"]
    assert inserted.rows[0]["name"] == "Acme"
    assert inserted.last_id == item_id
    assert db.fetch_one("SELECT name FROM items WHERE id = ?", (item_id,))["name"] == "Acme"
    updated = db.execute(
        "UPDATE items SET n = ? WHERE id = ? RETURNING n",
        (5, item_id),
    )
    assert updated.rowcount == 1
    assert updated.rows[0]["n"] == 5
    deleted = db.execute("DELETE FROM items WHERE id = ?", (item_id,))
    assert deleted.rowcount == 1
    assert db.fetch_one("SELECT id FROM items WHERE id = ?", (item_id,)) is None


def test_insert_on_conflict_do_update_returning() -> None:
    db = fresh()
    first = db.execute(
        "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?) RETURNING id, n",
        ("Acme", 1, 1, STAMP),
    )
    second = db.execute(
        """
        INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET n = excluded.n
        RETURNING id, name, n
        """,
        ("Acme", 4, 1, STAMP),
    )
    assert second.rows[0]["id"] == first.rows[0]["id"]
    assert second.rows[0]["name"] == "Acme"
    assert second.rows[0]["n"] == 4
    assert db.fetch_one("SELECT COUNT(*) AS c FROM items")["c"] == 1


def test_booleans_are_zero_one_and_timestamps_round_trip() -> None:
    db = fresh()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute(
        "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
        ("Acme", 1, 1, stamp),
    )
    db.execute(
        "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
        ("Off", 0, 0, stamp),
    )
    on_row = db.fetch_one("SELECT on_flag, ts FROM items WHERE name = ?", ("Acme",))
    off_row = db.fetch_one("SELECT on_flag FROM items WHERE name = ?", ("Off",))
    assert on_row is not None and off_row is not None
    assert on_row["on_flag"] == 1
    assert off_row["on_flag"] == 0
    assert on_row["ts"] == stamp


def test_icontains_matches_case_insensitively_without_like() -> None:
    db = fresh()
    db.execute(
        "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
        ("Acme Corp", 1, 1, STAMP),
    )
    db.execute(
        "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
        ("Other", 1, 0, STAMP),
    )
    fragment = db.dialect.icontains("name")
    assert "like" not in fragment.lower()
    rows = db.fetch_all(f"SELECT name FROM items WHERE {fragment} ORDER BY name", ("aCmE",))
    assert [row["name"] for row in rows] == ["Acme Corp"]


def test_unique_violation_does_not_insert() -> None:
    db = fresh()
    db.execute(
        "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
        ("Acme", 1, 1, STAMP),
    )
    with pytest.raises(UniqueViolation):
        db.execute(
            "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
            ("Acme", 2, 1, STAMP),
        )
    assert db.fetch_one("SELECT COUNT(*) AS c FROM items")["c"] == 1


def test_check_and_foreign_key_violations_are_mapped() -> None:
    db = fresh()
    with pytest.raises(CheckViolation):
        db.execute(
            "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
            ("Acme", -1, 1, STAMP),
        )
    with pytest.raises(ForeignKeyViolation):
        db.execute("INSERT INTO children (item_id) VALUES (?)", (99,))


def test_batch_commits_every_statement() -> None:
    db = fresh()
    results = db.batch(
        [
            Stmt(
                "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?) RETURNING name",
                ("Acme", 1, 1, STAMP),
            ),
            Stmt(
                "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?) RETURNING name",
                ("Other", 2, 0, STAMP),
            ),
        ]
    )
    assert results[0].rows[0]["name"] == "Acme"
    assert results[1].rows[0]["name"] == "Other"
    assert db.fetch_one("SELECT COUNT(*) AS c FROM items")["c"] == 2


def test_batch_rolls_back_when_the_second_statement_fails() -> None:
    db = fresh()
    with pytest.raises(UniqueViolation):
        db.batch(
            [
                Stmt(
                    "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
                    ("Acme", 1, 1, STAMP),
                ),
                Stmt(
                    "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
                    ("Acme", 2, 0, STAMP),
                ),
            ]
        )
    assert db.fetch_one("SELECT COUNT(*) AS c FROM items")["c"] == 0


def test_strict_d1_rejects_more_than_100_bound_parameters() -> None:
    db = SqliteDatabase(":memory:", strict_d1=True)
    params = tuple(range(101))
    sql = "SELECT " + "+".join("?" * 101)
    db.queries.reset()
    with pytest.raises(ParameterLimitError):
        db.fetch_one(sql, params)
    assert db.queries.count == 0
    allowed = db.fetch_one("SELECT " + "+".join("?" * 100), tuple(range(100)))
    assert allowed is not None
    assert next(iter(allowed.values())) == sum(range(100))


def test_strict_batch_rejects_before_any_write() -> None:
    db = fresh(strict_d1=True)
    wide = tuple(range(101))
    with pytest.raises(ParameterLimitError):
        db.batch(
            [
                Stmt(
                    "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
                    ("Acme", 1, 1, STAMP),
                ),
                Stmt("SELECT " + "+".join("?" * 101), wide),
            ]
        )
    assert db.fetch_one("SELECT COUNT(*) AS c FROM items")["c"] == 0


def test_non_strict_sqlite_allows_more_than_100_parameters() -> None:
    db = SqliteDatabase(":memory:", strict_d1=False)
    params = tuple(range(101))
    row = db.fetch_one("SELECT " + "+".join("?" * 101), params)
    assert row is not None
    assert next(iter(row.values())) == sum(params)


def test_locked_database_maps_to_transient_error() -> None:
    mapped = map_sqlite_error(sqlite3.OperationalError("database is locked"))
    assert isinstance(mapped, TransientError)
    assert map_sqlite_error(sqlite3.OperationalError("database is busy")) is not None
