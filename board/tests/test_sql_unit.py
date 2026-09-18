"""Postgres adapter + blob persistence (no SQLite, no Hub volume)."""

from __future__ import annotations

from pathlib import Path

from app.db import BoardDB
from app.metrics import MetricsStore
from app.sql import adapt_sql, schema_name_for_path


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
