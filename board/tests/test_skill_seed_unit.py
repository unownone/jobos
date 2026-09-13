"""Parse GitHub SKILL.md / starter YAML without booting FastAPI."""

from __future__ import annotations

from pathlib import Path

from app.skill_seed import iter_github_starters, parse_skill_md, split_frontmatter
from app.skill_store import url_matches


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


def test_url_matches_workday_host() -> None:
    patterns = ["*.myworkdayjobs.com/*"]
    assert url_matches("https://acme.myworkdayjobs.com/en-US/job/1", patterns)
    assert not url_matches("https://boards.greenhouse.io/acme/jobs/1", patterns)
