"""Admin signup, candidate onboarding, session persistence, profile prefill."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from helpers import (
    CANDIDATE,
    assert_still_signed_in,
    fill_onboarding,
    skip_resume,
    signup_admin,
    unique_password,
    unique_username,
    upload_resume,
)


def test_signup_onboarding_stays_logged_in_and_prefills(page: Page) -> None:
    username = unique_username("admin")
    password = unique_password()
    signup_admin(page, username, password)
    fill_onboarding(page)
    expect(page.locator("#ok")).to_contain_text("Profile saved")
    assert_still_signed_in(page)

    skip_resume(page)
    expect(page).to_have_url(re.compile(r".*/board(?:$|[?#])"))
    expect(page.locator("#whoLabel")).to_contain_text(username, timeout=15_000)
    assert_still_signed_in(page)

    page.goto("/onboarding")
    expect(page.locator("#full_name")).to_have_value(CANDIDATE["full_name"], timeout=15_000)
    expect(page.locator("#email")).to_have_value(CANDIDATE["email"])
    expect(page.locator("#titles")).to_have_value(CANDIDATE["titles"])
    expect(page.locator("#locations_t")).to_have_value(CANDIDATE["locations"])
    expect(page.locator("#headline")).to_have_value(CANDIDATE["headline"])
    expect(page.locator("#stack")).to_have_value(CANDIDATE["stack"])
    expect(page.locator("#revLine")).to_contain_text("revision")
    assert_still_signed_in(page)

    page.click("#to2")
    page.click("#to3")
    page.click("#save")
    expect(page.locator("#ok")).to_contain_text("Profile saved")
    assert_still_signed_in(page)
    upload_resume(page)
    expect(page).to_have_url(re.compile(r".*/board(?:$|[?#])"))
    expect(page.locator("#whoLabel")).to_contain_text(username)
    assert_still_signed_in(page)

    page.goto("/")
    expect(page.locator('a[href="/board"]')).to_contain_text("Open board", timeout=10_000)
    page.click('a[href="/board"]')
    page.wait_for_url("**/board", timeout=15_000)
    assert_still_signed_in(page)


def test_onboarding_validates_required_fields(page: Page) -> None:
    signup_admin(page, unique_username("val"), unique_password())
    page.click("#to2")
    expect(page.locator("#err")).to_contain_text("Full name and email")
    page.fill("#full_name", "Pat Kim")
    page.fill("#email", "pat.e2e@example.test")
    page.click("#to2")
    expect(page.locator("#step2")).to_be_visible()
    page.click("#to3")
    expect(page.locator("#err")).to_contain_text("title")
    assert_still_signed_in(page)


def test_login_rejects_bad_password(page: Page) -> None:
    username = unique_username("bad")
    password = unique_password()
    signup_admin(page, username, password)
    page.click("[data-hub-logout]")
    page.wait_for_url("**/login**", timeout=15_000)
    page.fill("#username", username)
    page.fill("#password", "wrong-password")
    page.click("button[type='submit']")
    expect(page.locator("#err")).not_to_have_text("", timeout=10_000)
    expect(page).to_have_url(re.compile(r".*/login(?:$|[?#])"))


def test_logout_then_board_requires_login(page: Page) -> None:
    username = unique_username("out")
    password = unique_password()
    signup_admin(page, username, password)
    fill_onboarding(page)
    skip_resume(page)
    page.click("#logoutBtn")
    page.wait_for_url("**/login**", timeout=15_000)
    page.goto("/board")
    page.wait_for_url("**/login**", timeout=15_000)
    login = page.request.get("/api/auth/me")
    assert login.status == 401
