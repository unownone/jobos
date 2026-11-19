"""Postgres adapter + blob persistence (no SQLite, no Hub volume)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import psycopg
import pytest

from app.db import BoardDB
from app.metrics import MetricsStore
from app.sql import adapt_sql, connect_params, schema_name_for_path


def _backend_pid(db: BoardDB) -> int:
    return int(db.conn.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])


def _drop_session(db: BoardDB) -> int:
    """Kill the Hub's server session, as Neon does when a compute scales to zero."""
    pid = _backend_pid(db)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (pid,))
        deadline = time.monotonic() + 10
        while admin.execute("SELECT 1 FROM pg_stat_activity WHERE pid = %s", (pid,)).fetchone():
            assert time.monotonic() < deadline, "backend did not exit"
            time.sleep(0.02)
    return pid


def _session_state(pid: int) -> str:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as admin:
        row = admin.execute("SELECT state FROM pg_stat_activity WHERE pid = %s", (pid,)).fetchone()
    return row[0]


def _insert_kv(db: BoardDB, key: str) -> None:
    db.conn.execute(
        "INSERT INTO hub_kv (key, value, updated_at) VALUES (?, ?, ?)", (key, "v", "t")
    )


def test_adapt_sql_qmark_and_named() -> None:
    sql, params = adapt_sql("SELECT * FROM jobs WHERE id = ?", ("abc",))
    assert "%s" in sql
    assert "?" not in sql
    assert params == ("abc",)
    sql, params = adapt_sql("UPDATE jobs SET title = :title WHERE id = :id", {"title": "T", "id": "1"})
    assert sql.count("%s") == 2
    assert params == ("T", "1")
    sql, params = adapt_sql("SELECT 1 FROM x WHERE pod LIKE 'track:%' AND id = ?", ("a",))
    assert "%%" in sql
    assert params == ("a",)


def test_schema_names_differ_per_path(tmp_path: Path) -> None:
    a = schema_name_for_path(tmp_path / "one.db")
    b = schema_name_for_path(tmp_path / "two.db")
    assert a != b
    assert a.startswith("s")


def test_jobs_and_events_roundtrip(tmp_path: Path) -> None:
    db = BoardDB(tmp_path / "board.db")
    tenant = db.compat_tenant
    job = db.insert_job(tenant, {"id": "gh__pg1", "company": "Acme", "title": "Staff"})
    assert job["id"] == "gh__pg1"
    event = db.add_event(
        tenant,
        job_id=job["id"],
        actor_role="discovery",
        actor="pytest",
        action="created",
    )
    assert event["id"]
    assert db.get_job(tenant, "gh__pg1")["company"] == "Acme"
    assert db.list_events(tenant, job_id="gh__pg1")[0]["action"] == "created"
    db.close()


def test_connect_params_fill_only_what_the_url_leaves_out() -> None:
    neon = (
        "postgresql://app:pw@ep-x-pooler.ap-southeast-1.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require"
    )
    assert connect_params(neon) == {
        "connect_timeout": "10",
        "keepalives": "1",
        "keepalives_idle": "30",
        "keepalives_interval": "10",
        "keepalives_count": "3",
    }
    assert "connect_timeout" not in connect_params(neon + "&connect_timeout=3")
    assert "keepalives_idle" not in connect_params("host=db dbname=jobos keepalives_idle=60")


def test_reads_and_writes_survive_a_dropped_session(tmp_path: Path) -> None:
    db = BoardDB(tmp_path / "board.db")
    tenant = db.compat_tenant
    db.insert_job(tenant, {"id": "gh__drop1", "company": "Acme", "title": "Staff"})
    first = _drop_session(db)
    assert db.get_job(tenant, "gh__drop1")["company"] == "Acme"
    assert _backend_pid(db) != first
    _drop_session(db)
    db.insert_job(tenant, {"id": "gh__drop2", "company": "Beta", "title": "Staff"})
    db.close()
    again = BoardDB(tmp_path / "board.db")
    assert again.get_job(again.compat_tenant, "gh__drop2")["company"] == "Beta"
    again.close()


def test_reads_leave_the_session_idle_not_in_transaction(tmp_path: Path) -> None:
    db = BoardDB(tmp_path / "board.db")
    tenant = db.compat_tenant
    db.insert_job(tenant, {"id": "gh__idle1", "company": "Acme", "title": "Staff"})
    db.get_job(tenant, "gh__idle1")
    db.list_jobs(tenant)
    assert _session_state(_backend_pid(db)) == "idle"
    _insert_kv(db, "idle.pending")
    assert _session_state(_backend_pid(db)) == "idle in transaction"
    assert db.get_kv("idle.pending") == "v"
    db.conn.commit()
    db.close()


def test_session_lost_mid_transaction_is_never_half_committed(tmp_path: Path) -> None:
    db = BoardDB(tmp_path / "board.db")
    _insert_kv(db, "tx.first")
    _drop_session(db)
    with pytest.raises(psycopg.OperationalError):
        _insert_kv(db, "tx.second")
    with pytest.raises(psycopg.OperationalError, match="nothing was committed"):
        db.conn.commit()
    assert db.get_kv("tx.first") is None
    assert db.get_kv("tx.second") is None
    db.put_kv("tx.after", "ok")
    assert db.get_kv("tx.after") == "ok"
    db.close()


def test_read_that_notices_a_lost_transaction_blocks_its_commit(tmp_path: Path) -> None:
    db = BoardDB(tmp_path / "board.db")
    _insert_kv(db, "shared.first")
    _drop_session(db)
    # Another request on the shared connection hits the dead session first.
    with pytest.raises(psycopg.OperationalError):
        db.get_kv("shared.first")
    _insert_kv(db, "shared.second")
    with pytest.raises(psycopg.OperationalError, match="nothing was committed"):
        db.conn.commit()
    assert db.get_kv("shared.first") is None
    assert db.get_kv("shared.second") is None
    db.close()


def test_commit_or_rollback_on_a_dropped_session_then_recovers(tmp_path: Path) -> None:
    db = BoardDB(tmp_path / "board.db")
    _insert_kv(db, "commit.lost")
    _drop_session(db)
    with pytest.raises(psycopg.OperationalError):
        db.conn.commit()
    assert db.get_kv("commit.lost") is None

    _insert_kv(db, "rollback.lost")
    _drop_session(db)
    with pytest.raises(psycopg.OperationalError):
        _insert_kv(db, "rollback.second")
    db.rollback()
    db.put_kv("rollback.after", "ok")
    assert db.get_kv("rollback.lost") is None
    assert db.get_kv("rollback.after") == "ok"
    db.close()


def test_closed_connection_does_not_reconnect(tmp_path: Path) -> None:
    db = BoardDB(tmp_path / "board.db")
    db.close()
    with pytest.raises(psycopg.OperationalError):
        db.get_kv("anything")


def test_schema_isolation(tmp_path: Path) -> None:
    a = BoardDB(tmp_path / "a.db")
    b = BoardDB(tmp_path / "b.db")
    a.insert_job(a.compat_tenant, {"id": "gh__only_a", "company": "A", "title": "One"})
    assert b.get_job(b.compat_tenant, "gh__only_a") is None
    assert a.get_job(a.compat_tenant, "gh__only_a") is not None
    a.close()
    b.close()


def test_blobs_and_kv_survive_reconnect(tmp_path: Path) -> None:
    path = tmp_path / "board.db"
    db = BoardDB(path)
    db.put_blob(
        db.compat_tenant,
        "candidate.yaml",
        b"identity:\n  full_name: Test\n",
        content_type="text/yaml",
    )
    db.put_kv("bootstrap.token", "jh_boot_keepme")
    db.close()
    again = BoardDB(path)
    blob = again.get_blob(again.compat_tenant, "candidate.yaml")
    assert blob is not None
    assert b"full_name: Test" in blob["content"]
    assert again.get_kv("bootstrap.token") == "jh_boot_keepme"
    again.close()


def test_bootstrap_plaintext_survives_missing_env_files(tmp_path: Path) -> None:
    from app.bootstrap import BOOTSTRAP_PLAIN_KEY, ensure_bootstrap
    from app.settings import Settings

    settings = Settings(
        board_dir=tmp_path,
        db_path=tmp_path / "board.db",
        host="127.0.0.1",
        port=8787,
        tokens={},
        env_path=tmp_path / ".env",
        tokens_json_path=tmp_path / "tokens.local.json",
    )
    db = BoardDB(settings.db_path)
    token = ensure_bootstrap(settings, db)
    assert token
    assert db.get_kv(BOOTSTRAP_PLAIN_KEY) == token
    settings.env_path.unlink()
    settings.tokens_json_path.unlink()
    db.close()
    again = BoardDB(settings.db_path)
    recovered = ensure_bootstrap(
        Settings(
            board_dir=tmp_path,
            db_path=tmp_path / "board.db",
            host="127.0.0.1",
            port=8787,
            tokens={},
            bootstrap_token="",
            env_path=tmp_path / ".env",
            tokens_json_path=tmp_path / "tokens.local.json",
        ),
        again,
    )
    assert recovered == token
    again.close()
    db = BoardDB(tmp_path / "metrics.db")
    metrics = MetricsStore(db.conn)
    row = metrics.record_token_burn({"tool_name": "exa", "prompt_tokens": 7, "completion_tokens": 3})
    assert row["id"]
    assert row["total_tokens"] == 10
    summary = metrics.summary()
    assert summary["n"] == 1
    assert summary["totals"]["total_tokens"] == 10
    db.close()
