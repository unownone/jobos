"""Shared Hub test fixtures. Autouse a truthful-enough candidate so operational APIs are ungated."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def postgres_server(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Embedded Postgres for the whole pytest process. Hub no longer uses SQLite."""
    existing = (os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if existing:
        os.environ["TEST_DATABASE_URL"] = existing
        os.environ["DATABASE_URL"] = existing
        yield existing
        return
    import pgserver

    data_dir = tmp_path_factory.mktemp("pgdata")
    server = pgserver.get_server(data_dir, cleanup_mode="stop")
    uri = server.get_uri()
    os.environ["TEST_DATABASE_URL"] = uri
    os.environ["DATABASE_URL"] = uri
    try:
        yield uri
    finally:
        server.cleanup()

MINIMAL_CANDIDATE = """\
identity:
  full_name: "Test Candidate"
  preferred_name: "Test"
  email: "test.candidate@example.test"
  phone: ""
  location: "Remote"
  timezone: "UTC"
  work_authorization: "test fixture; not a live hunt"
  linkedin_url: ""
  github_url: ""
  portfolio_url: ""
  website: ""

target:
  titles:
    - "Staff Software Engineer"
  seniority: ["staff"]
  domains: ["test"]
  locations:
    - "Remote"
  remote: "required"
  salary_floor_usd: 0
  visa_needs: false
  company_sizes: ["startup"]
  must_haves:
    - "Writes production code"
  deal_breakers:
    - "Unpaid trial projects"

proof:
  headline: "Test fixture profile"
  years_experience: 1
  stack: ["Python"]
  highlights:
    - "Fixture only"
  do_not_claim:
    - "Anything not in this fixture"

materials:
  resume_primary: "assets/resume/resume-primary.pdf"
  resume_variants: []
  writing_voice: "Direct"

constraints:
  max_discovers_per_cycle: 40
  max_shortlist_per_cycle: 12
  max_applies_per_day: 8
  max_outreach_touches_per_person: 2
  easy_apply_policy: "never during discovery"
"""


@pytest.fixture(autouse=True)
def seed_hub_candidate(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    if request.node.get_closest_marker("no_candidate"):
        return
    dest = tmp_path / "data" / "profiles" / "candidate.yaml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(MINIMAL_CANDIDATE, encoding="utf-8")
    # Tests that set Settings.db_path = tmp_path / "board.db" persist next to sqlite.
    alt = tmp_path / "profiles" / "candidate.yaml"
    alt.parent.mkdir(parents=True, exist_ok=True)
    alt.write_text(MINIMAL_CANDIDATE, encoding="utf-8")
    # Default Settings.db_path is tmp_path/board.db so hub path is tmp_path/profiles/...
    # Also cover tmp_path/board.db parent.


# Modules that do not boot the FastAPI app (CI `test` job).
_UNIT_MODULE_NAMES = frozenset(
    {
        "test_urls.py",
        "test_tokens.py",
        "test_unauth_secrets_unit.py",
        "test_auth_gate_helpers.py",
        "test_briefing_unit.py",
        "test_invite_prompt_unit.py",
        "test_ui_shell.py",
    }
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Split unit vs in-process HTTP e2e so CI jobs stay distinct.

    ``*e2e*`` modules and ``test_unauth_apis.py`` are e2e. Named unit modules
    stay unit. Remaining TestClient suites are e2e (in-process FastAPI; no
    extra server or browser install).
    """
    e2e = pytest.mark.e2e
    unit = pytest.mark.unit
    for item in items:
        name = Path(str(item.path)).name
        if "e2e" in name or name == "test_unauth_apis.py":
            item.add_marker(e2e)
        elif name in _UNIT_MODULE_NAMES or name.endswith("_unit.py"):
            item.add_marker(unit)
        else:
            item.add_marker(e2e)
