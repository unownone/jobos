"""Apply the sqlite migrations and check the postgres files when a server is up."""

from __future__ import annotations

import os
import re
import sqlite3
import uuid
from pathlib import Path

import psycopg
import pytest

from app.storage.migrate import apply_sqlite, split_sql

pytestmark = pytest.mark.unit

BOARD = Path(__file__).resolve().parents[1]
SQLITE_DIR = BOARD / "migrations" / "sqlite"
POSTGRES_DIR = BOARD / "migrations" / "postgres"

REQUIRED_INDEXES = (
    "idx_sessions_token_hash",
    "idx_sessions_account_seen",
    "idx_jobs_status_updated",
    "idx_queue_claim",
    "idx_events_account_actor",
    "idx_events_account_action",
    "idx_events_account_ts",
    "idx_presence_account_hb",
    "idx_messages_account_to_user",
    "idx_messages_account_to_track",
    "idx_memory_recall",
    "idx_burn_account_id",
    "idx_a2a_peers_account_card",
    "idx_queue_items_account_dedupe",
)

_INDEX_SQL = re.compile(r"^CREATE (?:UNIQUE )?INDEX[^;]*;", re.M)


def _read_dir(directory: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.sql")))


_SQLITE_ID_DEFAULT = "DEFAULT (lower(hex(randomblob(16))))"
_POSTGRES_ID_DEFAULT = "DEFAULT (gen_random_uuid()::text)"


def _ddl(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _normalize_generated_ids(sql: str) -> str:
    return sql.replace(_SQLITE_ID_DEFAULT, "DEFAULT (__TEXT_ID__)").replace(
        _POSTGRES_ID_DEFAULT, "DEFAULT (__TEXT_ID__)"
    )


def _sqlite_index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


def test_split_sql_ignores_comments_and_keeps_string_semicolons() -> None:
    parts = split_sql(
        "-- comment;\nCREATE TABLE a (id TEXT); /* semi; */\n"
        "INSERT INTO a (id) VALUES ('a;b');\n"
    )
    assert parts == [
        "CREATE TABLE a (id TEXT)",
        "INSERT INTO a (id) VALUES ('a;b')",
    ]


def test_portable_type_rules_and_baseline_parity() -> None:
    sqlite_sql = _read_dir(SQLITE_DIR)
    postgres_sql = _read_dir(POSTGRES_DIR)
    sqlite_ddl = _ddl(sqlite_sql)
    postgres_ddl = _ddl(postgres_sql)
    assert re.search(r"\bBYTEA\b", sqlite_ddl, re.I) is None
    assert re.search(r"\bBLOB\b", sqlite_ddl, re.I)
    assert re.search(r"\bBYTEA\b", postgres_ddl, re.I)
    assert re.search(r"\bBLOB\b", postgres_ddl, re.I) is None
    for ddl in (sqlite_ddl, postgres_ddl):
        upper = ddl.upper()
        assert "GENERATED" not in upper
        assert "IDENTITY" not in upper
        assert "BOOLEAN" not in upper
        assert "BIGINT" not in upper
    sqlite_base = (SQLITE_DIR / "0001_baseline.sql").read_text(encoding="utf-8")
    postgres_base = (POSTGRES_DIR / "0001_baseline.sql").read_text(encoding="utf-8")
    assert sqlite_base.count(_SQLITE_ID_DEFAULT) == 2
    assert postgres_base.count(_POSTGRES_ID_DEFAULT) == 2
    assert _SQLITE_ID_DEFAULT not in postgres_base
    assert _POSTGRES_ID_DEFAULT not in sqlite_base
    assert re.sub(r"\s+", " ", _normalize_generated_ids(_ddl(sqlite_base))).strip() == re.sub(
        r"\s+", " ", _normalize_generated_ids(_ddl(postgres_base).replace("BYTEA", "BLOB"))
    ).strip()
    assert _INDEX_SQL.findall(
        (SQLITE_DIR / "0002_indexes_and_constraints.sql").read_text(encoding="utf-8")
    ) == _INDEX_SQL.findall(
        (POSTGRES_DIR / "0002_indexes_and_constraints.sql").read_text(encoding="utf-8")
    )


def test_sqlite_migrations_create_indexes_and_check(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "hub.sqlite")
    try:
        applied = apply_sqlite(conn, SQLITE_DIR)
        assert applied == ["0001_baseline.sql", "0002_indexes_and_constraints.sql"]
        assert apply_sqlite(conn, SQLITE_DIR) == []
        names = _sqlite_index_names(conn)
        missing = [name for name in REQUIRED_INDEXES if name not in names]
        assert missing == []
        assert "idx_invites_track" in names
        assert "idx_queue_account_dedupe" in names
        assert "idx_queue_items_account_dedupe" in names
        dedupe_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'idx_queue_items_account_dedupe'"
        ).fetchone()[0]
        assert "UNIQUE" in dedupe_sql.upper()
        assert "WHERE" not in dedupe_sql.upper()
        versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
        assert versions == ["0001_baseline.sql", "0002_indexes_and_constraints.sql"]
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "outbox" in tables
        assert "processed_messages" in tables
        assert "invites__redemptions_chk" not in tables
        assert "a2a_peers__account_card" not in tables
        events_id = conn.execute("PRAGMA table_info(events)").fetchall()
        assert events_id[0][1] == "id" and events_id[0][2].upper() == "TEXT"
        burn_id = conn.execute("PRAGMA table_info(token_burn)").fetchall()
        assert burn_id[0][1] == "id" and burn_id[0][2].upper() == "TEXT"
        conn.execute(
            """
            INSERT INTO events (account_id, ts, actor_role, action)
            VALUES ('acc_evt', '2020-01-01T00:00:00Z', 'discovery', 'noted')
            """
        )
        event_id = conn.execute("SELECT id FROM events WHERE account_id = 'acc_evt'").fetchone()[0]
        assert isinstance(event_id, str) and event_id
        conn.execute(
            """
            INSERT INTO token_burn (ts, tool_name)
            VALUES ('2020-01-01T00:00:00Z', 'search')
            """
        )
        burn_row_id = conn.execute(
            "SELECT id FROM token_burn WHERE tool_name = 'search'"
        ).fetchone()[0]
        assert isinstance(burn_row_id, str) and burn_row_id
        blob = conn.execute("PRAGMA table_info(hub_blobs)").fetchall()
        content = next(row for row in blob if row[1] == "content")
        assert content[2].upper() == "BLOB"
        invite_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'invites'"
        ).fetchone()[0]
        assert "redemptions <= max_redemptions" in invite_sql
        conn.execute(
            """
            INSERT INTO invites (
                id, account_id, track, mode, secret_hash, max_redemptions, redemptions,
                expires_at, created_at
            ) VALUES ('inv_ok', 'acc', 'discovery', 'single', 'h', 2, 2, '2099-01-01T00:00:00Z', '2020-01-01T00:00:00Z')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO invites (
                    id, account_id, track, mode, secret_hash, max_redemptions, redemptions,
                    expires_at, created_at
                ) VALUES ('inv_bad', 'acc', 'discovery', 'single', 'h', 1, 2, '2099-01-01T00:00:00Z', '2020-01-01T00:00:00Z')
                """
            )
        conn.execute(
            """
            INSERT INTO outbox (id, account_id, topic, body_json, created_at)
            VALUES ('ob1', 'acc', 'queue', '{}', '2020-01-01T00:00:00Z')
            """
        )
        conn.execute(
            "INSERT INTO processed_messages (id, processed_at) VALUES ('msg1', '2020-01-01T00:00:00Z')"
        )
        peer_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'a2a_peers'"
        ).fetchone()[0]
        assert "UNIQUE" not in peer_sql.upper()
        conn.execute(
            """
            INSERT INTO queue_items (id, account_id, kind, status, dedupe_key, created_at)
            VALUES ('q1', 'acc', 'discovery.search', 'open', 'same', '2020-01-01T00:00:00Z')
            ON CONFLICT(account_id, dedupe_key) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO queue_items (id, account_id, kind, status, dedupe_key, created_at)
            VALUES ('q2', 'acc', 'discovery.search', 'open', 'same', '2020-01-01T00:00:00Z')
            ON CONFLICT(account_id, dedupe_key) DO NOTHING
            """
        )
        queued = conn.execute(
            "SELECT COUNT(*) FROM queue_items WHERE account_id = 'acc' AND dedupe_key = 'same'"
        ).fetchone()[0]
        assert queued == 1
        conn.execute(
            """
            INSERT INTO a2a_peers (id, account_id, card_url, created_at)
            VALUES ('p1', 'acc_a', 'https://agent.example/card', '2020-01-01T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO a2a_peers (id, account_id, card_url, created_at)
            VALUES ('p2', 'acc_b', 'https://agent.example/card', '2020-01-01T00:00:00Z')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO a2a_peers (id, account_id, card_url, created_at)
                VALUES ('p3', 'acc_a', 'https://agent.example/card', '2020-01-01T00:00:00Z')
                """
            )
    finally:
        conn.close()


def test_failed_migration_rolls_back_and_is_not_recorded(tmp_path: Path) -> None:
    mig = tmp_path / "sql"
    mig.mkdir()
    (mig / "0001_bad.sql").write_text(
        "CREATE TABLE good (id TEXT PRIMARY KEY);\nINSERT INTO missing(id) VALUES ('x');\n",
        encoding="utf-8",
    )
    conn = sqlite3.connect(tmp_path / "t.sqlite")
    try:
        with pytest.raises(sqlite3.Error):
            apply_sqlite(conn, mig)
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "good" not in tables
        versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations")]
        assert versions == []
    finally:
        conn.close()


def test_apply_sqlite_rejects_an_open_transaction(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "open.sqlite")
    try:
        conn.execute("BEGIN")
        with pytest.raises(RuntimeError, match="no open transaction"):
            apply_sqlite(conn, SQLITE_DIR)
    finally:
        conn.close()


def test_app_modules_do_not_apply_migrations() -> None:
    app = BOARD / "app"
    offenders: list[str] = []
    for path in app.rglob("*.py"):
        if path.name == "migrate.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "apply_sqlite" in text or "schema_migrations" in text or "migrations/sqlite" in text:
            offenders.append(str(path.relative_to(BOARD)))
    assert offenders == []


def test_postgres_migration_parity() -> None:
    url = (os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        pytest.skip("no postgres server")
    schema = "mig_parity_" + uuid.uuid4().hex
    try:
        conn = psycopg.connect(url, autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"no postgres server: {exc}")
    try:
        conn.execute(f"CREATE SCHEMA {schema}")
        conn.execute(f"SET search_path TO {schema}")
        try:
            for path in sorted(POSTGRES_DIR.glob("*.sql")):
                for statement in split_sql(path.read_text(encoding="utf-8")):
                    conn.execute(statement)
            rows = conn.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = %s",
                (schema,),
            ).fetchall()
            names = {row[0] for row in rows}
            missing = [name for name in REQUIRED_INDEXES if name not in names]
            assert missing == []
            id_types = dict(
                conn.execute(
                    """
                    SELECT table_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = %s AND column_name = 'id'
                      AND table_name IN ('events', 'token_burn')
                    """,
                    (schema,),
                ).fetchall()
            )
            assert id_types == {"events": "text", "token_burn": "text"}
            blob = conn.execute(
                """
                SELECT data_type FROM information_schema.columns
                WHERE table_schema = %s AND table_name = 'hub_blobs' AND column_name = 'content'
                """,
                (schema,),
            ).fetchone()
            assert blob is not None and blob[0] == "bytea"
            check = conn.execute(
                """
                SELECT c.conname
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = %s AND t.relname = 'invites' AND c.contype = 'c'
                """,
                (schema,),
            ).fetchone()
            assert check is not None and check[0] == "invites_redemptions_lte_max"
            with pytest.raises(psycopg.Error):
                conn.execute(
                    """
                    INSERT INTO invites (
                        id, account_id, track, mode, secret_hash, max_redemptions,
                        redemptions, expires_at, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        "inv_bad",
                        "acc",
                        "discovery",
                        "single",
                        "h",
                        1,
                        2,
                        "2099-01-01T00:00:00Z",
                        "2020-01-01T00:00:00Z",
                    ),
                )
            conn.execute(
                """
                INSERT INTO outbox (id, account_id, topic, body_json, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                ("ob1", "acc", "queue", "{}", "2020-01-01T00:00:00Z"),
            )
            conn.execute(
                "INSERT INTO processed_messages (id, processed_at) VALUES (%s, %s)",
                ("msg1", "2020-01-01T00:00:00Z"),
            )
            dedupe_def = conn.execute(
                """
                SELECT indexdef FROM pg_indexes
                WHERE schemaname = %s AND indexname = 'idx_queue_items_account_dedupe'
                """,
                (schema,),
            ).fetchone()
            assert dedupe_def is not None
            assert "UNIQUE" in dedupe_def[0].upper()
            assert "WHERE" not in dedupe_def[0].upper()
            card_unique = conn.execute(
                """
                SELECT c.conname
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = %s AND t.relname = 'a2a_peers'
                  AND c.contype = 'u' AND c.conname = 'a2a_peers_card_url_key'
                """,
                (schema,),
            ).fetchone()
            assert card_unique is None
            conn.execute(
                """
                INSERT INTO queue_items (id, account_id, kind, status, dedupe_key, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(account_id, dedupe_key) DO NOTHING
                """,
                ("q1", "acc", "discovery.search", "open", "same", "2020-01-01T00:00:00Z"),
            )
            conn.execute(
                """
                INSERT INTO queue_items (id, account_id, kind, status, dedupe_key, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(account_id, dedupe_key) DO NOTHING
                """,
                ("q2", "acc", "discovery.search", "open", "same", "2020-01-01T00:00:00Z"),
            )
            queued = conn.execute(
                "SELECT COUNT(*) FROM queue_items WHERE account_id = %s AND dedupe_key = %s",
                ("acc", "same"),
            ).fetchone()
            assert queued is not None and queued[0] == 1
            conn.execute(
                """
                INSERT INTO a2a_peers (id, account_id, card_url, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                ("p1", "acc_a", "https://agent.example/card", "2020-01-01T00:00:00Z"),
            )
            conn.execute(
                """
                INSERT INTO a2a_peers (id, account_id, card_url, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                ("p2", "acc_b", "https://agent.example/card", "2020-01-01T00:00:00Z"),
            )
            with pytest.raises(psycopg.Error):
                conn.execute(
                    """
                    INSERT INTO a2a_peers (id, account_id, card_url, created_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    ("p3", "acc_a", "https://agent.example/card", "2020-01-01T00:00:00Z"),
                )
        finally:
            conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    finally:
        conn.close()
