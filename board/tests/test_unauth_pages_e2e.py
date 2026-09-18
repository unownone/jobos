"""E2E: unauthenticated browser/HTTP access to Job Hub pages must be denied.

These tests encode the security contract. They fail while HTML shells for the
job board, admin, candidate onboarding, and user directory are served without a
session. They pass only after those routes redirect to /login (or 401/403) and
do not include candidate/job canaries.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unauth_support import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    BROWSER_HEADERS,
    JOB_COMPANY,
    PROTECTED_PAGES,
    SeededHub,
    assert_unauthenticated_denied,
    make_seeded_hub,
)


@pytest.fixture()
def seeded(tmp_path: Path) -> SeededHub:
    return make_seeded_hub(tmp_path)


@pytest.mark.parametrize(
    "path,what",
    PROTECTED_PAGES,
    ids=[item[1].replace(" ", "-") for item in PROTECTED_PAGES],
)
def test_unauthenticated_browser_cannot_open_sensitive_page(
    seeded: SeededHub,
    path: str,
    what: str,
) -> None:
    res = seeded.unauth.get(path, headers=BROWSER_HEADERS)
    assert_unauthenticated_denied(res, what=what)


def test_unauthenticated_direct_url_job_board_is_not_a_200_with_board_ui(
    seeded: SeededHub,
) -> None:
    res = seeded.unauth.get("/board", headers=BROWSER_HEADERS)
    assert_unauthenticated_denied(res, what="job board /board")
    body = (res.text or "").lower()
    if res.status_code == 200:
        assert "job hub" not in body, "unauthenticated job board page returned 200 with Job Hub UI"


def test_unauthenticated_direct_url_admin_is_denied(seeded: SeededHub) -> None:
    res = seeded.unauth.get("/admin", headers=BROWSER_HEADERS)
    assert_unauthenticated_denied(res, what="admin dashboard /admin")
    assert res.status_code != 200, (
        "unauthenticated admin dashboard returned 200 with admin HTML"
    )


def test_unauthenticated_direct_url_candidate_onboarding_is_denied(
    seeded: SeededHub,
) -> None:
    res = seeded.unauth.get("/onboarding", headers=BROWSER_HEADERS)
    assert_unauthenticated_denied(res, what="candidate onboarding page")


def test_unauthenticated_direct_url_users_directory_is_denied(seeded: SeededHub) -> None:
    res = seeded.unauth.get("/admin/users", headers=BROWSER_HEADERS)
    assert_unauthenticated_denied(res, what="admin users directory page")


def test_login_page_stays_reachable_and_does_not_embed_canaries(
    seeded: SeededHub,
) -> None:
    res = seeded.unauth.get("/login", headers=BROWSER_HEADERS)
    assert res.status_code == 200, res.text
    body = res.text
    assert JOB_COMPANY not in body
    assert "canary-live-token-" not in body
    assert "Admin login" in body or "login" in body.lower()


def test_unauthenticated_can_load_hub_css_and_js(seeded: SeededHub) -> None:
    css = seeded.unauth.get("/static/hub.css")
    assert css.status_code == 200, css.text[:200]
    assert "text/css" in css.headers.get("content-type", "")
    assert "--paper" in css.text
    assert "jobOS Harness — Login" not in css.text
    js = seeded.unauth.get("/static/hub.js")
    assert js.status_code == 200, js.text[:200]
    assert "csrfToken" in js.text
    html = seeded.unauth.get("/static/index.html", headers=BROWSER_HEADERS)
    assert_unauthenticated_denied(html, what="job board static HTML")


def test_authenticated_session_control_can_open_job_board_api(
    seeded: SeededHub,
) -> None:
    """Control: login exists and an authenticated session can still read jobs."""
    seeded.authed.cookies.clear()
    denied = seeded.authed.get("/api/jobs")
    assert denied.status_code == 401
    login = seeded.authed.post(
        "/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert login.status_code == 200, login.text
    listed = seeded.authed.get("/api/jobs")
    assert listed.status_code == 200, listed.text
    companies = [job.get("company") for job in listed.json().get("jobs", [])]
    assert JOB_COMPANY in companies


def test_authenticated_session_can_open_skills_and_memory_pages(
    seeded: SeededHub,
) -> None:
    login = seeded.authed.post(
        "/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert login.status_code == 200, login.text
    skills = seeded.authed.get("/admin/skills", headers=BROWSER_HEADERS)
    assert skills.status_code == 200, skills.text
    assert "Skill registry" in skills.text
    assert JOB_COMPANY not in skills.text
    memory = seeded.authed.get("/admin/memory", headers=BROWSER_HEADERS)
    assert memory.status_code == 200, memory.text
    assert "Memory pods" in memory.text
    assert "data-solidify" in memory.text
    assert 'id="add-item"' in memory.text
    assert "data-delete" in memory.text
