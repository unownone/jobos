"""Operator shell: every authenticated Hub page and its primary actions."""

from __future__ import annotations

from playwright.sync_api import Page, expect

from helpers import (
    api,
    fill_onboarding,
    skip_resume,
    signup_admin,
    unique_password,
    unique_username,
)


def _onboarded_admin(page: Page) -> str:
    username = unique_username("shell")
    signup_admin(page, username, unique_password())
    fill_onboarding(page)
    skip_resume(page)
    return username


def test_nav_pages_load_for_admin(page: Page) -> None:
    _onboarded_admin(page)
    pages = [
        ("/board", "#whoLabel"),
        ("/admin", "#who"),
        ("/admin/users", "#who"),
        ("/admin/data", "#who"),
        ("/admin/skills", "#who"),
        ("/admin/memory", "#who"),
        ("/onboarding", "#who"),
    ]
    for path, who in pages:
        page.goto(path)
        expect(page.locator(who)).not_to_contain_text("Checking session", timeout=15_000)
        expect(page.locator(who)).not_to_contain_text("signing in")
    page.goto("/board")
    expect(page.locator("#whoLabel")).to_contain_text("admin", timeout=15_000)
    expect(page.locator("#list")).not_to_contain_text("Sign in as the Hub admin")


def test_invites_skills_memory_and_data_tabs(page: Page) -> None:
    _onboarded_admin(page)

    page.goto("/admin")
    expect(page.locator("#soon")).to_contain_text("review", timeout=10_000)
    page.select_option("#track", "outreach")
    page.click("form#form button[type='submit']")
    expect(page.locator("#created")).to_contain_text("/join/", timeout=15_000)
    expect(page.locator("#prompt")).not_to_be_empty()
    expect(page.locator("#rows")).to_contain_text("outreach")
    page.locator("#rows button", has_text="Revoke").first.click()
    expect(page.locator("#rows")).to_contain_text("revoked", timeout=10_000)

    page.goto("/admin/skills")
    expect(page.locator("#skills")).to_contain_text("job-discovery", timeout=15_000)
    page.select_option("#tag", "source")
    page.click("#reload")
    expect(page.locator("#skills")).to_contain_text("source")
    page.click("#seed")
    expect(page.locator("#msg")).to_contain_text("Seeded", timeout=20_000)

    page.goto("/admin/memory")
    page.wait_for_function("() => document.querySelectorAll('#write-pod option').length > 0")
    values = page.eval_on_selector_all("#write-pod option", "els => els.map(e => e.value)")
    target = next((v for v in values if v == "track:discovery"), None) or next(
        (v for v in values if v == "common" or str(v).startswith("track:")), None
    )
    assert target, values
    page.select_option("#write-pod", target)
    page.wait_for_function("() => document.querySelectorAll('#write-kind option').length > 0")
    page.fill("#write-title", "Greenhouse work-auth radio")
    page.fill("#write-body", "The portal asks for work authorization on page two. Do not guess the legal answer.")
    page.click("#add-item")
    expect(page.locator("#compose-status")).to_contain_text("Stored", timeout=15_000)
    expect(page.locator("#rows")).to_contain_text("Greenhouse work-auth radio")
    page.click("button[data-edit]")
    page.fill("#write-title", "Greenhouse work-auth radio (updated)")
    page.click("#save-item")
    expect(page.locator("#compose-status")).to_contain_text("Updated", timeout=15_000)
    expect(page.locator("#rows")).to_contain_text("(updated)")

    page.goto("/admin/data?tab=skills")
    expect(page.locator("#table")).to_contain_text("job-discovery", timeout=15_000)
    page.click('[data-tab="mcps"]')
    expect(page.locator("#table")).to_contain_text("gmail", timeout=15_000)
    page.click('[data-tab="candidate"]')
    expect(page.locator("#stats")).to_contain_text("onboarded", timeout=15_000)


def test_board_job_ticket_patch_pause_resume(page: Page) -> None:
    username = _onboarded_admin(page)
    created = api(
        page,
        "POST",
        "/api/jobs",
        body={
            "id": f"e2e__{username}-ticket",
            "company": "TicketCo",
            "title": "Staff SRE",
            "status": "discovered",
            "location": "Remote",
            "apply_url": "https://jobs.example.test/sre",
        },
    )
    assert created["status"] == 201, created
    page.goto("/board")
    expect(page.locator("#list")).to_contain_text("TicketCo", timeout=15_000)
    page.locator("#list tr", has_text="TicketCo").click()
    expect(page.locator("#f_company")).to_have_value("TicketCo")
    page.fill("#f_notes", "Shortlisted for the e2e run.")
    page.click("#saveBtn")
    expect(page.locator("#sideErr")).to_contain_text("Saved", timeout=10_000)

    page.once("dialog", lambda dialog: dialog.accept("e2e pause"))
    page.click("#pauseBtn")
    expect(page.locator("#list")).to_contain_text("stopped", timeout=10_000)
    page.locator("#list tr", has_text="TicketCo").click()
    page.click("#resumeBtn")
    expect(page.locator("#f_company")).to_have_value("TicketCo", timeout=10_000)


def test_agent_pack_messages_export_and_a2a(page: Page) -> None:
    _onboarded_admin(page)
    meta = api(page, "GET", "/api/meta")
    assert meta["status"] == 200
    assert "registry" in meta["body"]
    onboarding = api(page, "GET", "/api/onboarding?track=discovery")
    assert onboarding["status"] == 200, onboarding
    assert any(row.get("name") == "job-discovery" for row in onboarding["body"].get("skills") or [])

    posted = api(
        page,
        "POST",
        "/api/messages",
        body={"type": "note", "body": "e2e ping from admin", "to_track": "discovery"},
    )
    assert posted["status"] in {200, 201}, posted
    listed = api(page, "GET", "/api/messages")
    assert listed["status"] == 200
    export = page.request.get("/api/export/ledger")
    assert export.status in {200, 409} or export.ok
    a2a = page.request.get("/a2a")
    assert a2a.ok
    peers = api(page, "GET", "/api/a2a/directory")
    assert peers["status"] in {200, 401, 403}

    who = api(page, "GET", "/api/whoami")
    assert who["status"] == 200, who
    events = api(page, "GET", "/api/events")
    assert events["status"] == 200, events
    hygiene = api(page, "GET", "/api/hygiene")
    assert hygiene["status"] == 200, hygiene
    ready = page.request.get("/ready")
    assert ready.ok
    assert ready.json().get("ready") is True
    burns = api(
        page,
        "POST",
        "/api/metrics/token_burn",
        body={
            "tool_name": "e2e",
            "skill": "job-discovery",
            "lane": "discovery",
            "prompt_tokens": 10,
            "completion_tokens": 4,
            "total_tokens": 14,
        },
    )
    assert burns["status"] in {200, 201}, burns
    listed_burns = api(page, "GET", "/api/metrics/token_burn")
    assert listed_burns["status"] == 200, listed_burns
    summary = api(page, "GET", "/api/metrics/summary")
    assert summary["status"] == 200, summary
    imported = api(
        page,
        "POST",
        "/api/import",
        body={
            "jobs": [
                {
                    "id": "e2e__imported",
                    "company": "ImportCo",
                    "title": "Staff Import",
                    "status": "discovered",
                }
            ]
        },
    )
    assert imported["status"] in {200, 201}, imported
