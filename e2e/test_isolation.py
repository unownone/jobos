"""Two admins must not see or write each other's tenant data."""

from __future__ import annotations

from playwright.sync_api import Browser, expect

from helpers import (
    api,
    fill_onboarding,
    skip_resume,
    signup_admin,
    unique_password,
    unique_username,
)


def test_two_admins_do_not_cross_write(browser: Browser, base_url: str) -> None:
    alice_name = unique_username("alice")
    bob_name = unique_username("bobby")
    alice_pass = unique_password()
    bob_pass = unique_password()

    alice_ctx = browser.new_context(base_url=base_url)
    bob_ctx = browser.new_context(base_url=base_url)
    alice = alice_ctx.new_page()
    bob = bob_ctx.new_page()
    try:
        signup_admin(alice, alice_name, alice_pass)
        fill_onboarding(
            alice,
            {
                "full_name": "Alice Hunt",
                "email": "alice.e2e@example.test",
                "titles": "Staff Platform Engineer",
            },
        )
        skip_resume(alice)

        signup_admin(bob, bob_name, bob_pass)
        fill_onboarding(
            bob,
            {
                "full_name": "Bob Hunt",
                "email": "bob.e2e@example.test",
                "titles": "Senior ML Engineer",
            },
        )
        skip_resume(bob)

        created = api(
            alice,
            "POST",
            "/api/jobs",
            body={
                "id": f"e2e__{alice_name}",
                "company": "AliceOnlyCo",
                "title": "Staff Platform",
                "status": "discovered",
            },
        )
        assert created["status"] == 201, created

        alice_jobs = api(alice, "GET", "/api/jobs")
        assert alice_jobs["status"] == 200
        assert any(job.get("company") == "AliceOnlyCo" for job in alice_jobs["body"].get("jobs", []))

        bob_jobs = api(bob, "GET", "/api/jobs")
        assert bob_jobs["status"] == 200, bob_jobs
        assert all(job.get("company") != "AliceOnlyCo" for job in bob_jobs["body"].get("jobs", []))

        stolen = api(bob, "GET", f"/api/jobs/e2e__{alice_name}")
        assert stolen["status"] == 404

        alice.goto("/onboarding")
        expect(alice.locator("#full_name")).to_have_value("Alice Hunt", timeout=15_000)
        expect(alice.locator("#titles")).to_have_value("Staff Platform Engineer")

        bob.goto("/onboarding")
        expect(bob.locator("#full_name")).to_have_value("Bob Hunt", timeout=15_000)
        expect(bob.locator("#titles")).to_have_value("Senior ML Engineer")
        expect(bob.locator("#full_name")).not_to_have_value("Alice Hunt")

        alice.goto("/board")
        expect(alice.locator("#list")).to_contain_text("AliceOnlyCo", timeout=15_000)
        bob.goto("/board")
        expect(bob.locator("#list")).not_to_contain_text("AliceOnlyCo")
        expect(bob.locator("#whoLabel")).to_contain_text(bob_name)
    finally:
        alice_ctx.close()
        bob_ctx.close()
