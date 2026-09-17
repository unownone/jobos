"""Parse skills/lists + mcp.example.json and upsert into a fresh Hub DB."""

from __future__ import annotations

from pathlib import Path

from app.db import BoardDB
from app.mcp_seed import iter_github_mcps, iter_list_mcps
from app.registry_seed import seed_hub_registries


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
    n_skills = int(db.conn.execute("SELECT COUNT(*) AS n FROM skills").fetchone()["n"])
    n_mcps = int(db.conn.execute("SELECT COUNT(*) AS n FROM mcps").fetchone()["n"])
    assert n_skills > 0
    assert n_mcps > 0
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
