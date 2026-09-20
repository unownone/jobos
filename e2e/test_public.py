"""Public marketing and unauthenticated surfaces."""

from __future__ import annotations

from playwright.sync_api import Page, expect


def test_landing_and_get_started_are_public(page: Page) -> None:
    page.goto("/")
    expect(page.locator("h1")).to_contain_text("Find jobs")
    expect(page.locator('a[href="/login"]')).to_be_visible()
    page.goto("/start")
    expect(page.locator("h1")).to_contain_text("Get started")
    expect(page.locator("body")).to_contain_text("candidate_required")


def test_login_page_is_public(page: Page) -> None:
    page.goto("/login")
    expect(page.locator("#username")).to_be_visible()
    expect(page.locator("#signupBtn")).to_contain_text("Create account")


def test_unauthenticated_board_redirects_to_login(page: Page) -> None:
    page.goto("/board")
    page.wait_for_url("**/login**", timeout=15_000)
    expect(page.locator("#username")).to_be_visible()


def test_unauthenticated_admin_and_onboarding_redirect(page: Page) -> None:
    page.goto("/admin")
    page.wait_for_url("**/login**", timeout=15_000)
    page.goto("/onboarding")
    page.wait_for_url("**/login**", timeout=15_000)


def test_health_and_agent_text_are_public(page: Page) -> None:
    health = page.request.get("/health")
    assert health.ok
    body = health.json()
    assert body["ok"] is True
    llms = page.request.get("/llms.txt")
    assert llms.ok
    assert "jobOS" in llms.text() or "hub" in llms.text().lower()
    agents = page.request.get("/agents.txt")
    assert agents.ok
    card = page.request.get("/.well-known/agent-card.json")
    assert card.ok
