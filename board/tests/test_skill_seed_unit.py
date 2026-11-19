"""Parse GitHub SKILL.md / starter YAML without booting FastAPI."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.skill_seed import iter_github_starters, parse_skill_md, split_frontmatter
from app.skill_store import url_matches
from app.storage.repos.registry import (
    SKILL_SUMMARY_COLUMNS,
    SkillRepo,
    apply_skill_schema,
)


def test_split_frontmatter_reads_name() -> None:
    front, body = split_frontmatter("---\nname: demo\nrole: apply\n---\n\n# Hello\n")
    assert front["name"] == "demo"
    assert body.startswith("# Hello")


def test_parse_os_job_apply(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    path = repo / "skills" / "job-apply" / "SKILL.md"
    parsed = parse_skill_md(path, repo_root=repo)
    assert parsed is not None
    assert parsed["slug"] == "job-apply"
    assert parsed["role"] == "apply"
    assert "apply" in parsed["tags"]
    assert "submit" in parsed["body"].lower() or "Apply" in parsed["body"]


def test_iter_starters_includes_role_skills() -> None:
    repo = Path(__file__).resolve().parents[2]
    slugs = {row["slug"] for row in iter_github_starters(repo)}
    assert {"job-discovery", "job-apply", "job-outreach", "skill-maintainer"} <= slugs
    assert {"apply-workday", "source-linkedin", "outreach-email"} <= slugs
    assert {"compose-outreach", "draft-outreach", "playwright-cli-skill"} <= slugs


def test_url_matches_workday_host() -> None:
    patterns = ["*.myworkdayjobs.com/*"]
    assert url_matches("https://acme.myworkdayjobs.com/en-US/job/1", patterns)
    assert not url_matches("https://boards.greenhouse.io/acme/jobs/1", patterns)


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


def test_skill_summary_columns_and_list_sql_omit_body_md() -> None:
    assert "body_md" not in SKILL_SUMMARY_COLUMNS
    conn = _Conn()
    repo = SkillRepo(conn)
    repo.list_admin_summary("acc", 10)
    repo.list_maintainer_summary("acc", "user", 10)
    repo.list_member_summary("acc", "user", 10)
    repo.list_approved_shared_summary("acc", 10)
    assert len(conn.statements) == 4
    for sql in conn.statements:
        folded = sql.upper()
        assert "BODY_MD" not in folded
        assert "SELECT *" not in folded
    repo.get_skill("acc", "skl_demo")
    assert "body_md" in conn.statements[-1]
    repo.skill_bodies("acc", ["skl_demo", "skl_other"])
    assert "body_md" in conn.statements[-1]
    assert "SELECT *" not in conn.statements[-1].upper()


def _skill_fields() -> dict[str, object]:
    return {
        "id": "skl_demo",
        "slug": "demo",
        "name": "Demo",
        "kind": "skill",
        "role": "apply",
        "tags": ["apply", "workday"],
        "scope": "shared",
        "owner_user_id": None,
        "status": "approved",
        "platform": "workday",
        "match": {"ats": ["workday"], "url_patterns": [], "apply_kind": []},
        "inputs": ["job"],
        "outputs": ["proof"],
        "body": "BODY-MARKER req id",
        "origin": "github",
        "origin_ref": "skills/demo/SKILL.md",
        "parent_skill_id": None,
        "version": 1,
        "content_hash": "hash-1",
        "reproducible": True,
        "proctor_status": "passed",
        "proctor_note": "",
        "proctor_evidence": {},
        "approved_at": "2020-01-01T00:00:00Z",
        "approved_by": "github",
        "created_at": "2020-01-01T00:00:00Z",
        "updated_at": "2020-01-01T00:00:00Z",
        "created_by": "github",
    }


def test_sqlite_list_omits_body_and_get_returns_it(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "skills.db")
    conn.row_factory = sqlite3.Row
    apply_skill_schema(conn)
    repo = SkillRepo(conn)
    fields = _skill_fields()
    repo.insert_skill("acc", fields)
    conn.commit()
    listed = repo.list_approved_shared_summary("acc", 10)
    assert len(listed) == 1
    assert "body_md" not in listed[0]
    assert listed[0]["slug"] == "demo"
    assert listed[0]["tags_json"] == '["apply", "workday"]'
    full = repo.get_skill("acc", "skl_demo")
    assert full is not None
    assert full["body_md"] == "BODY-MARKER req id"
    assert repo.skill_bodies("acc", ["skl_demo"]) == {"skl_demo": "BODY-MARKER req id"}
    fields["body"] = "updated req"
    fields["content_hash"] = "hash-2"
    repo.update_skill("acc", "skl_demo", fields, updated_at="2020-01-02T00:00:00Z")
    fields["body"] = "other tenant"
    repo.update_skill("other", "skl_demo", fields, updated_at="2020-01-03T00:00:00Z")
    conn.commit()
    kept = repo.get_skill("acc", "skl_demo")
    assert kept is not None
    assert kept["body_md"] == "updated req"
    assert kept["updated_at"] == "2020-01-02T00:00:00Z"
