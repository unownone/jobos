"""Invite a worker, join, execute track tasks, observe them on the Hub."""

from __future__ import annotations

from playwright.sync_api import Page, expect

from helpers import (
    api,
    create_invite,
    fill_onboarding,
    join_worker,
    skip_resume,
    signup_admin,
    unique_password,
    unique_username,
)


def test_join_blocked_until_candidate_onboarded(page: Page, context) -> None:
    username = unique_username("pre")
    password = unique_password()
    signup_admin(page, username, password)
    # Invites are 409 until onboarded. Confirm jobs are gated, then onboard.
    denied = api(page, "POST", "/api/invites", body={"track": "discovery", "max_redemptions": 2})
    assert denied["status"] == 409
    assert denied["body"]["detail"]["code"] == "candidate_required"
    fill_onboarding(page)
    skip_resume(page)
    join_url = create_invite(page, "discovery")
    worker = context.new_page()
    worker.goto(join_url)
    expect(worker.locator("#form")).to_be_visible(timeout=15_000)
    worker.close()


def test_worker_joins_posts_job_claims_queue_and_shows_in_directory(page: Page, context) -> None:
    username = unique_username("ops")
    password = unique_password()
    signup_admin(page, username, password)
    fill_onboarding(page)
    skip_resume(page)

    join_url = create_invite(page, "discovery")
    worker_page = context.new_page()
    key = join_worker(worker_page, join_url, f"disc-{username}")
    worker_page.close()

    beat = api(
        page,
        "POST",
        "/api/presence/heartbeat",
        token=key,
        body={"status_hint": "working", "task_kind": "discovery.search"},
    )
    assert beat["status"] == 200, beat

    job = api(
        page,
        "POST",
        "/api/jobs",
        token=key,
        body={
            "id": f"e2e__{username}",
            "company": "E2E Co",
            "title": "Staff Backend Engineer",
            "apply_url": "https://jobs.example.test/staff",
            "location": "Remote",
            "status": "discovered",
            "sources": ["e2e"],
            "score": 4,
        },
    )
    assert job["status"] == 201, job

    pushed = api(
        page,
        "POST",
        "/api/queue/push",
        token=key,
        body={"kind": "catalog.refresh", "payload": {"reason": "e2e"}},
    )
    assert pushed["status"] == 200, pushed
    catalog = api(page, "POST", "/api/queue/claim", token=key, body={"kinds": ["catalog.refresh"], "limit": 1})
    assert catalog["status"] == 200, catalog
    catalog_items = catalog["body"].get("items") or []
    if catalog_items:
        acked_catalog = api(page, "POST", f"/api/queue/ack/{catalog_items[0]['id']}", token=key)
        assert acked_catalog["status"] == 200, acked_catalog

    pushed = api(
        page,
        "POST",
        "/api/queue/push",
        token=key,
        body={"kind": "discovery.search", "payload": {"portal": "wellfound", "query": username}},
    )
    assert pushed["status"] == 200, pushed
    claimed = api(page, "POST", "/api/queue/claim", token=key, body={"limit": 4})
    assert claimed["status"] == 200, claimed
    items = claimed["body"].get("items") or []
    assert items, claimed
    acked = api(page, "POST", f"/api/queue/ack/{items[0]['id']}", token=key)
    assert acked["status"] == 200, acked

    memory = api(
        page,
        "POST",
        "/api/memory/items",
        token=key,
        body={
            "pod": "worker",
            "kind": "fact",
            "title": "E2E Wellfound pagination",
            "body": "Public search is enough; do not click Easy Apply during discovery.",
        },
    )
    assert memory["status"] in {200, 201}, memory

    person = api(
        page,
        "POST",
        "/api/people",
        body={
            "id": f"e2e__hm-{username}",
            "name": "Hiring Manager",
            "company": "E2E Co",
            "title": "Eng Manager",
            "job_id": f"e2e__{username}",
        },
    )
    assert person["status"] == 201, person

    page.goto("/board")
    expect(page.locator("#list")).to_contain_text("E2E Co", timeout=15_000)
    page.fill("#q", "E2E Co")
    page.click("#refresh")
    expect(page.locator("#list")).to_contain_text("Staff Backend Engineer")

    page.goto("/admin/users")
    expect(page.locator("#rows")).to_contain_text(f"disc-{username}", timeout=15_000)

    page.goto("/admin/data?tab=jobs")
    expect(page.locator("#table")).to_contain_text("E2E Co", timeout=15_000)
    page.click('[data-tab="people"]')
    expect(page.locator("#table")).to_contain_text("Hiring Manager", timeout=15_000)
    page.click('[data-tab="candidate"]')
    expect(page.locator("#table")).to_contain_text("Staff Software Engineer", timeout=15_000)
    page.click('[data-tab="memory"]')
    expect(page.locator("#table")).to_contain_text("Wellfound", timeout=15_000)
