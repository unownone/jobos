"""Parse skills/lists + mcp.example.json and upsert into a fresh Hub DB."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db import BoardDB
from app.mcp_seed import iter_github_mcps, iter_list_mcps
from app.registry_seed import seed_hub_registries
from app.storage.repos.registry import MCP_COLUMNS, McpRepo, apply_mcp_schema


def _repo() -> Path:
    return Path(__file__).resolve().parents[2]


def test_list_mcps_include_adopted_and_rejected() -> None:
    rows = iter_list_mcps(_repo())
    slugs = {row["slug"] for row in rows}
    assert "exa-mcp" in slugs
    assert "gmail-mcp" in slugs
    assert "smartlead-instantly" in slugs
    exa = next(row for row in rows if row["slug"] == "exa-mcp")
    assert exa["status"] == "adopted"
    assert exa["kind"] == "mcp"
    assert exa["origin"] == "github"
    rejected = next(row for row in rows if row["slug"] == "smartlead-instantly")
    assert rejected["status"] == "rejected"


def test_example_json_attaches_config() -> None:
    rows = {row["slug"]: row for row in iter_github_mcps(_repo())}
    assert rows["exa-mcp"]["config"]
    assert "url" in rows["exa-mcp"]["config"] or rows["exa-mcp"]["hosted"]
    assert rows["gmail-mcp"]["hosted"].endswith("google-workspace.json")


def test_fresh_db_seed_is_nonempty_and_idempotent(tmp_path: Path) -> None:
    db = BoardDB(tmp_path / "board.db")
    first = seed_hub_registries(db)
    assert first["skills"]["inserted"] > 0
    assert first["mcps"]["inserted"] > 0
    n_skills = int(db.conn.execute("SELECT COUNT(*) AS n FROM skills").fetchone()["n"])
    n_mcps = int(db.conn.execute("SELECT COUNT(*) AS n FROM mcps").fetchone()["n"])
    skill_ids = {row["id"] for row in db.conn.execute("SELECT id FROM skills")}
    mcp_ids = {row["id"] for row in db.conn.execute("SELECT id FROM mcps")}
    slugs = {row["slug"] for row in db.conn.execute("SELECT slug FROM mcps")}
    assert "exa-mcp" in slugs
    second = seed_hub_registries(db)
    assert second["skills"]["inserted"] == 0
    assert second["mcps"]["inserted"] == 0
    assert {row["id"] for row in db.conn.execute("SELECT id FROM skills")} == skill_ids
    assert {row["id"] for row in db.conn.execute("SELECT id FROM mcps")} == mcp_ids
    assert int(db.conn.execute("SELECT COUNT(*) AS n FROM skills").fetchone()["n"]) == n_skills
    assert int(db.conn.execute("SELECT COUNT(*) AS n FROM mcps").fetchone()["n"]) == n_mcps


class _Cursor:
    def fetchall(self) -> list[dict[str, str]]:
        return []

    def fetchone(self) -> None:
        return None


class _Conn:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str, params: object = ()) -> _Cursor:
        del params
        self.statements.append(" ".join(sql.split()))
        return _Cursor()


def test_mcp_list_sql_names_columns() -> None:
    assert "body_md" not in MCP_COLUMNS
    conn = _Conn()
    repo = McpRepo(conn)
    repo.list_mcps("acc", 20)
    sql = conn.statements[-1].upper()
    assert "SELECT *" not in sql
    assert "FROM MCPS" in sql
    assert "LIMIT" in sql


def test_sqlite_mcp_list_keeps_notes(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "mcps.db")
    conn.row_factory = sqlite3.Row
    apply_mcp_schema(conn)
    repo = McpRepo(conn)
    repo.insert_mcp(
        "acc",
        {
            "id": "mcp_demo",
            "slug": "demo-mcp",
            "name": "Demo",
            "kind": "mcp",
            "status": "adopted",
            "verdict": "use",
            "capability": ["search"],
            "roles": ["discovery"],
            "platforms": [],
            "source": "test",
            "install": "",
            "auth": "",
            "notes": "keep this note",
            "reason": "",
            "next_action": "",
            "config": {"url": "https://example.test"},
            "hosted": "",
            "origin": "github",
            "origin_ref": "mcp/mcp.example.json",
            "version": 1,
            "content_hash": "hash",
            "created_at": "2020-01-01T00:00:00Z",
            "updated_at": "2020-01-01T00:00:00Z",
        },
    )
    conn.commit()
    rows = repo.list_mcps("acc", 10)
    assert rows[0]["notes"] == "keep this note"
    assert rows[0]["slug"] == "demo-mcp"
    repo.update_mcp(
        "other",
        "mcp_demo",
        {
            "slug": "demo-mcp",
            "name": "Demo",
            "kind": "mcp",
            "status": "rejected",
            "verdict": "reject",
            "capability": [],
            "roles": [],
            "platforms": [],
            "source": "",
            "install": "",
            "auth": "",
            "notes": "hijack",
            "reason": "",
            "next_action": "",
            "config": {},
            "hosted": "",
            "origin": "github",
            "origin_ref": "",
            "version": 2,
            "content_hash": "hash-2",
        },
        updated_at="2020-01-02T00:00:00Z",
    )
    conn.commit()
    kept = repo.get("acc", "mcp_demo")
    assert kept is not None
    assert kept["notes"] == "keep this note"
    assert kept["status"] == "adopted"
