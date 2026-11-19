"""Postgres adapter contract.

Unit tests mock the driver and always run. Behaviors shared with the SQLite
contract run against TEST_DATABASE_URL or embedded pgserver, and skip when
Postgres cannot start.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timezone

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.storage.errors import (
    CheckViolation,
    ForeignKeyViolation,
    StorageError,
    TransientError,
    UniqueViolation,
)
from app.storage.port import Stmt
from app.storage.postgres import PostgresDatabase

try:
    import pgserver
except ImportError:  # pragma: no cover - optional embedded server
    pgserver = None

STAMP = "2020-01-01T00:00:00Z"
SCHEMA = "storage_postgres_adapter"


class FakeCursor:
    def __init__(
        self,
        rows: list[dict[str, object]],
        *,
        rowcount: int,
        description: tuple[str, ...] | None,
    ) -> None:
        self._rows = rows
        self.rowcount = rowcount
        self.description = description

    def fetchall(self) -> list[dict[str, object]]:
        return list(self._rows)


class FakeTransaction:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    def __enter__(self) -> FakeTransaction:
        self._conn.transaction_starts += 1
        self._conn.open_transactions += 1
        self._conn.max_open_transactions = max(
            self._conn.max_open_transactions, self._conn.open_transactions
        )
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: object) -> bool:
        self._conn.open_transactions -= 1
        if exc_type is None:
            self._conn.commits += 1
        else:
            self._conn.rollbacks += 1
        return False


class FakeConnection:
    """Enough of a psycopg connection to exercise the adapter with no database."""

    def __init__(self, script: list[FakeCursor | Exception] | None = None) -> None:
        self.script = list(script or [])
        self.statements: list[tuple[str, tuple[object, ...]]] = []
        self.closed = False
        self.transaction_starts = 0
        self.open_transactions = 0
        self.max_open_transactions = 0
        self.commits = 0
        self.rollbacks = 0
        self.autocommit = False

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> FakeCursor:
        self.statements.append((sql, tuple(params)))
        if not self.script:
            return FakeCursor([], rowcount=1, description=None)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    def close(self) -> None:
        self.closed = True


def _cursor(
    rows: list[dict[str, object]] | None = None,
    *,
    rowcount: int = 1,
    description: tuple[str, ...] | None = ("n",),
) -> FakeCursor:
    return FakeCursor(list(rows or []), rowcount=rowcount, description=description)


def _install(monkeypatch: pytest.MonkeyPatch, connect: Callable[..., FakeConnection]) -> None:
    monkeypatch.setattr("app.storage.postgres.psycopg.connect", connect)


def _database(monkeypatch: pytest.MonkeyPatch, conn: FakeConnection) -> PostgresDatabase:
    _install(monkeypatch, lambda *args, **kwargs: conn)
    return PostgresDatabase("postgresql://unused")


@pytest.mark.unit
def test_dialect_icontains_uses_strpos_lower(monkeypatch: pytest.MonkeyPatch) -> None:
    def connect(*args: object, **kwargs: object) -> FakeConnection:
        raise AssertionError("reading the dialect must not open a connection")

    _install(monkeypatch, connect)
    db = PostgresDatabase("postgresql://unused")
    fragment = db.dialect.icontains("name")
    assert db.dialect.name == "postgres"
    assert db.dialect.placeholder == "%s"
    assert db.dialect.max_params == 65535
    assert db.dialect.skip_locked == "SKIP LOCKED"
    assert fragment == "strpos(lower(name), lower(%s)) > 0"
    assert "like" not in fragment.lower()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("sql", "params", "expected"),
    [
        (
            "INSERT INTO items (name) VALUES (?)",
            ("Acme",),
            "INSERT INTO items (name) VALUES (%s)",
        ),
        (
            "SELECT id FROM items WHERE a = ? AND b = ?",
            (1, "O'Hara"),
            "SELECT id FROM items WHERE a = %s AND b = %s",
        ),
        ("SELECT '?'", (), "SELECT '?'"),
        ("SELECT '100%'", (), "SELECT '100%%'"),
        (
            "strpos(lower(name), lower(%s)) > 0",
            ("aCmE",),
            "strpos(lower(name), lower(%s)) > 0",
        ),
        (
            "WHERE id = ? AND strpos(lower(name), lower(%s)) > 0",
            (4, "aCmE"),
            "WHERE id = %s AND strpos(lower(name), lower(%s)) > 0",
        ),
        ("SELECT n % 2", (), "SELECT n %% 2"),
        ("SELECT ? -- really?", (1,), "SELECT %s -- really?"),
        ("SELECT $q$what? 100%$q$", (), "SELECT $q$what? 100%%$q$"),
    ],
)
def test_execute_translates_qmark_placeholders_for_psycopg(
    monkeypatch: pytest.MonkeyPatch,
    sql: str,
    params: tuple[object, ...],
    expected: str,
) -> None:
    conn = FakeConnection()
    db = _database(monkeypatch, conn)
    db.execute(sql, params)
    assert conn.statements == [(expected, tuple(params))]


@pytest.mark.unit
def test_empty_batch_does_not_open_a_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    def connect(*args: object, **kwargs: object) -> FakeConnection:
        raise AssertionError("empty batch must not connect")

    _install(monkeypatch, connect)
    db = PostgresDatabase("postgresql://unused")
    assert db.batch([]) == []
    assert db.queries.count == 0


@pytest.mark.unit
def test_query_counter_counts_each_statement_and_resets(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection(script=[_cursor([{"n": 1}]) for _ in range(5)])
    db = _database(monkeypatch, conn)
    assert db.queries.count == 0
    db.fetch_one("SELECT ? AS n", (1,))
    db.fetch_all("SELECT ? AS n", (1,))
    db.execute("SELECT ? AS n", (1,))
    db.batch([Stmt("SELECT ? AS n", (1,)), Stmt("SELECT ? AS n", (2,))])
    assert db.queries.count == 5
    assert conn.transaction_starts == 4
    assert conn.max_open_transactions == 1
    db.queries.reset()
    assert db.queries.count == 0


@pytest.mark.unit
def test_execute_exposes_returning_rows_and_last_id(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection(
        script=[_cursor([{"id": 7, "name": "Acme"}], description=("id", "name"))]
    )
    db = _database(monkeypatch, conn)
    inserted = db.execute(
        "INSERT INTO items (name) VALUES (?) RETURNING id, name",
        ("Acme",),
    )
    assert inserted.rowcount == 1
    assert inserted.last_id == 7
    assert inserted.rows == ({"id": 7, "name": "Acme"},)
    missing = _database(
        monkeypatch,
        FakeConnection(script=[_cursor([], rowcount=0, description=("name",))]),
    )
    assert missing.fetch_one("SELECT name FROM items WHERE id = ?", (7,)) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (psycopg.errors.UniqueViolation("duplicate key value"), UniqueViolation),
        (psycopg.errors.CheckViolation("check constraint"), CheckViolation),
        (psycopg.errors.ForeignKeyViolation("foreign key"), ForeignKeyViolation),
        (psycopg.errors.DeadlockDetected("deadlock detected"), TransientError),
        (psycopg.errors.SerializationFailure("could not serialize access"), TransientError),
        (psycopg.errors.LockNotAvailable("could not obtain lock"), TransientError),
    ],
)
def test_execute_maps_sqlstate_without_a_database(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected: type[StorageError],
) -> None:
    connects: list[FakeConnection] = []

    def connect(*args: object, **kwargs: object) -> FakeConnection:
        conn = FakeConnection(script=[error])
        connects.append(conn)
        return conn

    _install(monkeypatch, connect)
    db = PostgresDatabase("postgresql://unused")
    with pytest.raises(expected):
        db.execute("INSERT INTO items (name) VALUES (?)", ("Acme",))
    assert len(connects) == 1
    assert connects[0].statements == [("INSERT INTO items (name) VALUES (%s)", ("Acme",))]
    assert connects[0].rollbacks == 1
    assert db.queries.count == 1


@pytest.mark.unit
def test_programming_errors_are_not_rewritten(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection(script=[psycopg.errors.SyntaxError("syntax error")])
    db = _database(monkeypatch, conn)
    with pytest.raises(psycopg.Error) as raised:
        db.execute("NOT SQL")
    assert not isinstance(raised.value, StorageError)


@pytest.mark.unit
def test_single_statement_reconnects_once_after_a_dropped_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[FakeConnection] = []

    def connect(*args: object, **kwargs: object) -> FakeConnection:
        if not created:
            conn = FakeConnection(
                script=[psycopg.errors.ConnectionFailure("connection closed unexpectedly")]
            )
        else:
            conn = FakeConnection(script=[_cursor([{"n": 1}])])
        created.append(conn)
        return conn

    _install(monkeypatch, connect)
    db = PostgresDatabase("postgresql://unused")
    row = db.fetch_one("SELECT ? AS n", (1,))
    assert row == {"n": 1}
    assert len(created) == 2
    assert created[0].statements[0][0] == "SELECT %s AS n"
    assert db.queries.count == 2


class _CommitDrop(FakeTransaction):
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> bool:
        super().__exit__(exc_type, exc, tb)
        if exc_type is None:
            self._conn.closed = True
            raise psycopg.errors.ConnectionFailure("connection closed during commit")
        return False


class _CommitDropConnection(FakeConnection):
    def transaction(self) -> _CommitDrop:
        return _CommitDrop(self)


@pytest.mark.unit
def test_a_dropped_commit_is_not_replayed(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[FakeConnection] = []

    def connect(*args: object, **kwargs: object) -> FakeConnection:
        conn = _CommitDropConnection(
            script=[_cursor([{"id": 1}], description=("id",), rowcount=1)]
        )
        created.append(conn)
        return conn

    _install(monkeypatch, connect)
    db = PostgresDatabase("postgresql://unused")
    with pytest.raises(TransientError):
        db.execute("INSERT INTO items (name) VALUES (?)", ("Acme",))
    assert len(created) == 1
    assert created[0].statements == [("INSERT INTO items (name) VALUES (%s)", ("Acme",))]
    assert db.queries.count == 1


@pytest.mark.unit
def test_dropped_connection_is_transient_after_one_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[FakeConnection] = []

    def connect(*args: object, **kwargs: object) -> FakeConnection:
        conn = FakeConnection(script=[psycopg.InterfaceError("the connection is closed")])
        created.append(conn)
        return conn

    _install(monkeypatch, connect)
    db = PostgresDatabase("postgresql://unused")
    with pytest.raises(TransientError):
        db.execute("UPDATE items SET n = ?", (1,))
    assert len(created) == 2
    assert db.queries.count == 2


@pytest.mark.unit
def test_batch_is_one_transaction_and_does_not_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[FakeConnection] = []
    conn = FakeConnection(
        script=[
            _cursor([{"name": "Acme"}], description=("name",)),
            psycopg.errors.UniqueViolation("duplicate key value"),
        ]
    )

    def connect(*args: object, **kwargs: object) -> FakeConnection:
        created.append(conn)
        return conn

    _install(monkeypatch, connect)
    db = PostgresDatabase("postgresql://unused")
    with pytest.raises(UniqueViolation):
        db.batch(
            [
                Stmt(
                    "INSERT INTO items (name) VALUES (?) RETURNING name",
                    ("Acme",),
                ),
                Stmt("INSERT INTO items (name) VALUES (?)", ("Acme",)),
            ]
        )
    assert len(created) == 1
    assert conn.transaction_starts == 1
    assert conn.max_open_transactions == 1
    assert conn.rollbacks == 1
    assert conn.commits == 0
    assert [sql for sql, _params in conn.statements] == [
        "INSERT INTO items (name) VALUES (%s) RETURNING name",
        "INSERT INTO items (name) VALUES (%s)",
    ]
    assert db.queries.count == 2


@pytest.mark.unit
def test_batch_connection_loss_is_transient_and_does_not_open_another_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[FakeConnection] = []

    def connect(*args: object, **kwargs: object) -> FakeConnection:
        conn = FakeConnection(
            script=[psycopg.errors.AdminShutdown("terminating connection due to administrator command")]
        )
        created.append(conn)
        return conn

    _install(monkeypatch, connect)
    db = PostgresDatabase("postgresql://unused")
    with pytest.raises(TransientError):
        db.batch([Stmt("DELETE FROM items WHERE name = ?", ("Acme",))])
    assert len(created) == 1


def _skip_reason(url: str) -> str | None:
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:
        return f"Postgres cannot start: {exc}"
    return None


def _with_search_path(url: str) -> str:
    params = conninfo_to_dict(url)
    extra = f"-c search_path={SCHEMA}"
    current = str(params.get("options") or "")
    if extra not in current:
        params["options"] = f"{current} {extra}".strip()
    return make_conninfo(**params)


@pytest.fixture(scope="module")
def postgres_dsn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """TEST_DATABASE_URL when it answers, otherwise the embedded pgserver."""
    configured = (os.environ.get("TEST_DATABASE_URL") or "").strip()
    if configured:
        reason = _skip_reason(configured)
        if reason is not None:
            pytest.skip(reason)
        with psycopg.connect(configured, autocommit=True) as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        yield _with_search_path(configured)
        return

    if pgserver is None:
        pytest.skip(
            "Postgres cannot start: pgserver is not installed and TEST_DATABASE_URL is unset"
        )
    data_dir = tmp_path_factory.mktemp("postgres-adapter")
    try:
        server = pgserver.get_server(data_dir, cleanup_mode="stop")
        url = server.get_uri()
    except Exception as exc:
        pytest.skip(f"Postgres cannot start: {exc}")
    reason = _skip_reason(url)
    if reason is not None:
        server.cleanup()
        pytest.skip(reason)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    try:
        yield _with_search_path(url)
    finally:
        server.cleanup()


@pytest.fixture
def new_db(postgres_dsn: str) -> Iterator[Callable[[], PostgresDatabase]]:
    opened: list[PostgresDatabase] = []

    def open_db() -> PostgresDatabase:
        database = PostgresDatabase(postgres_dsn)
        opened.append(database)
        database.execute("DROP TABLE IF EXISTS children")
        database.execute("DROP TABLE IF EXISTS items")
        database.execute(
            """
            CREATE TABLE items (
                id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                n INTEGER NOT NULL CHECK (n >= 0),
                on_flag INTEGER NOT NULL,
                ts TEXT NOT NULL
            )
            """
        )
        database.execute(
            """
            CREATE TABLE children (
                id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                item_id INTEGER NOT NULL REFERENCES items(id)
            )
            """
        )
        database.queries.reset()
        return database

    yield open_db
    for database in opened:
        database.close()


def test_crud_returning_update_and_delete(new_db: Callable[[], PostgresDatabase]) -> None:
    db = new_db()
    inserted = db.execute(
        "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?) RETURNING id, name",
        ("Acme", 1, 1, STAMP),
    )
    assert inserted.rowcount == 1
    item_id = inserted.rows[0]["id"]
    assert inserted.rows[0]["name"] == "Acme"
    assert inserted.last_id == item_id
    assert db.fetch_one("SELECT name FROM items WHERE id = ?", (item_id,))["name"] == "Acme"
    updated = db.execute("UPDATE items SET n = ? WHERE id = ? RETURNING n", (5, item_id))
    assert updated.rowcount == 1
    assert updated.rows[0]["n"] == 5
    deleted = db.execute("DELETE FROM items WHERE id = ?", (item_id,))
    assert deleted.rowcount == 1
    assert db.fetch_one("SELECT id FROM items WHERE id = ?", (item_id,)) is None


def test_execute_is_visible_to_another_connection(
    new_db: Callable[[], PostgresDatabase], postgres_dsn: str
) -> None:
    writer = new_db()
    writer.execute(
        "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
        ("Acme", 1, 1, STAMP),
    )
    reader = PostgresDatabase(postgres_dsn)
    try:
        assert reader.fetch_one("SELECT name FROM items WHERE name = ?", ("Acme",))["name"] == "Acme"
    finally:
        reader.close()


def test_insert_on_conflict_do_update_returning(new_db: Callable[[], PostgresDatabase]) -> None:
    db = new_db()
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


def test_booleans_are_zero_one_and_timestamps_round_trip(
    new_db: Callable[[], PostgresDatabase],
) -> None:
    db = new_db()
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


def test_icontains_matches_case_insensitively_without_like(
    new_db: Callable[[], PostgresDatabase],
) -> None:
    db = new_db()
    db.execute(
        "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
        ("Acme Corp", 1, 1, STAMP),
    )
    db.execute(
        "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
        ("Other", 1, 0, STAMP),
    )
    fragment = db.dialect.icontains("name")
    assert fragment == "strpos(lower(name), lower(%s)) > 0"
    assert "like" not in fragment.lower()
    rows = db.fetch_all(f"SELECT name FROM items WHERE {fragment} ORDER BY name", ("aCmE",))
    assert [row["name"] for row in rows] == ["Acme Corp"]


def test_literal_percent_in_sql_and_parameters(new_db: Callable[[], PostgresDatabase]) -> None:
    db = new_db()
    db.execute(
        "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
        ("100%", 1, 1, STAMP),
    )
    assert db.fetch_one("SELECT name FROM items WHERE name = ?", ("100%",))["name"] == "100%"
    assert db.fetch_one("SELECT (n % 2) AS m FROM items WHERE name = ?", ("100%",))["m"] == 1


def test_unique_violation_does_not_insert(new_db: Callable[[], PostgresDatabase]) -> None:
    db = new_db()
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


def test_check_and_foreign_key_violations_are_mapped(
    new_db: Callable[[], PostgresDatabase],
) -> None:
    db = new_db()
    with pytest.raises(CheckViolation):
        db.execute(
            "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
            ("Acme", -1, 1, STAMP),
        )
    with pytest.raises(ForeignKeyViolation):
        db.execute("INSERT INTO children (item_id) VALUES (?)", (99,))


def test_batch_commits_every_statement(
    new_db: Callable[[], PostgresDatabase], postgres_dsn: str
) -> None:
    db = new_db()
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
    reader = PostgresDatabase(postgres_dsn)
    try:
        assert reader.fetch_one("SELECT COUNT(*) AS c FROM items")["c"] == 2
    finally:
        reader.close()


def test_batch_rolls_back_when_the_second_statement_fails(
    new_db: Callable[[], PostgresDatabase], postgres_dsn: str
) -> None:
    db = new_db()
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
    reader = PostgresDatabase(postgres_dsn)
    try:
        assert reader.fetch_one("SELECT COUNT(*) AS c FROM items")["c"] == 0
    finally:
        reader.close()


def test_more_than_one_hundred_parameters_are_allowed(
    new_db: Callable[[], PostgresDatabase],
) -> None:
    db = new_db()
    params = tuple(range(101))
    row = db.fetch_one("SELECT " + "+".join("?" * 101) + " AS n", params)
    assert row is not None
    assert row["n"] == sum(params)


def test_query_counter_matches_the_sqlite_contract(new_db: Callable[[], PostgresDatabase]) -> None:
    db = new_db()
    assert db.queries.count == 0
    db.fetch_one("SELECT 1 AS n")
    db.fetch_all("SELECT 1 AS n")
    db.execute("SELECT 1 AS n")
    db.batch([Stmt("SELECT 1 AS n"), Stmt("SELECT 2 AS n")])
    assert db.queries.count == 5
    db.queries.reset()
    assert db.queries.count == 0


def test_statement_reconnects_once_after_the_backend_is_terminated(
    new_db: Callable[[], PostgresDatabase], postgres_dsn: str
) -> None:
    db = new_db()
    db.execute(
        "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
        ("Acme", 1, 1, STAMP),
    )
    pid = int(db.fetch_one("SELECT pg_backend_pid() AS pid")["pid"])
    with psycopg.connect(postgres_dsn, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (pid,))
        deadline = time.monotonic() + 10
        while admin.execute("SELECT 1 FROM pg_stat_activity WHERE pid = %s", (pid,)).fetchone():
            if time.monotonic() > deadline:
                pytest.fail("backend did not exit after pg_terminate_backend")
            time.sleep(0.02)
    row = db.fetch_one("SELECT name FROM items WHERE name = ?", ("Acme",))
    assert row is not None
    assert row["name"] == "Acme"
    assert int(db.fetch_one("SELECT pg_backend_pid() AS pid")["pid"]) != pid


def test_question_mark_stored_as_data_round_trips(new_db: Callable[[], PostgresDatabase]) -> None:
    db = new_db()
    db.execute(
        "INSERT INTO items (name, n, on_flag, ts) VALUES (?, ?, ?, ?)",
        ("what?", 1, 0, STAMP),
    )
    assert db.fetch_one("SELECT name FROM items WHERE name = ?", ("what?",))["name"] == "what?"
