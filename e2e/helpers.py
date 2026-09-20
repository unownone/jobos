"""Shared Playwright helpers for Hub browser e2e."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from playwright.sync_api import APIRequestContext, Page, expect

ROOT = Path(__file__).resolve().parent
RESUME_PDF = ROOT / "fixtures" / "resume.pdf"

CANDIDATE = {
    "full_name": "Jordan Lee",
    "preferred_name": "Jordan",
    "email": "jordan.e2e@example.test",
    "phone": "+1-555-0100",
    "location": "Bengaluru, India",
    "timezone": "Asia/Kolkata",
    "work_authorization": "India citizen; open to remote",
    "linkedin_url": "https://www.linkedin.com/in/jordan-e2e",
    "github_url": "https://github.com/jordan-e2e",
    "titles": "Staff Software Engineer, Senior Backend Engineer",
    "locations": "Remote, Bengaluru",
    "seniority": "senior, staff",
    "domains": "developer tools, infra",
    "remote": "required-or-hybrid",
    "must_haves": "Writes production code\nOwns on-call",
    "deal_breakers": "Unpaid trial projects",
    "headline": "Staff engineer who ships backends",
    "years": "12",
    "stack": "Python, FastAPI, Postgres",
    "highlights": "Owns a production service\nReviews Hub PRs",
    "do_not_claim": "Anything not in this fixture",
    "writing_voice": "Direct, specific, no fluff",
}


def unique_username(prefix: str = "u") -> str:
    stamp = uuid.uuid4().hex[:10]
    return f"{prefix}{stamp}"


def unique_password() -> str:
    return f"s3cret-{uuid.uuid4().hex[:10]}"


def csrf_from_page(page: Page) -> str:
    raw = page.evaluate(
        """() => {
          const hit = document.cookie.split("; ").find((c) => c.startsWith("hub_csrf="));
          return hit ? decodeURIComponent(hit.split("=").slice(1).join("=")) : "";
        }"""
    )
    return str(raw or "")


def signup_admin(page: Page, username: str, password: str) -> None:
    page.goto("/login")
    expect(page.locator("#username")).to_be_visible()
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#signupBtn")
    page.wait_for_url("**/onboarding", timeout=20_000)
    expect(page.locator("#formPanel")).to_be_visible()
    expect(page.locator("#who")).to_contain_text("Signed in")


def login_admin(page: Page, username: str, password: str) -> None:
    page.goto("/login")
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("button[type='submit']")
    page.wait_for_url(re.compile(r".*/(onboarding|board)(?:$|[?#])"), timeout=20_000)


def fill_onboarding(page: Page, data: dict[str, str] | None = None, *, save: bool = True) -> None:
    values = dict(CANDIDATE)
    if data:
        values.update(data)
    expect(page.locator("#full_name")).to_be_visible()
    page.fill("#full_name", values["full_name"])
    page.fill("#preferred_name", values["preferred_name"])
    page.fill("#email", values["email"])
    page.fill("#phone", values["phone"])
    page.fill("#location", values["location"])
    page.fill("#timezone", values["timezone"])
    page.fill("#work_authorization", values["work_authorization"])
    page.fill("#linkedin_url", values["linkedin_url"])
    page.fill("#github_url", values["github_url"])
    page.click("#to2")
    page.fill("#titles", values["titles"])
    page.fill("#locations_t", values["locations"])
    page.fill("#seniority", values["seniority"])
    page.fill("#domains", values["domains"])
    page.fill("#remote", values["remote"])
    page.fill("#must_haves", values["must_haves"])
    page.fill("#deal_breakers", values["deal_breakers"])
    page.click("#to3")
    page.fill("#headline", values["headline"])
    page.fill("#years", values["years"])
    page.fill("#stack", values["stack"])
    page.fill("#highlights", values["highlights"])
    page.fill("#do_not_claim", values["do_not_claim"])
    page.fill("#writing_voice", values["writing_voice"])
    if save:
        page.click("#save")
        expect(page.locator("#ok")).to_contain_text("Profile saved", timeout=15_000)
        expect(page.locator("#step4")).to_be_visible()


def upload_resume(page: Page) -> None:
    expect(page.locator("#resume")).to_be_visible()
    page.set_input_files("#resume", str(RESUME_PDF))
    page.click("#uploadResume")
    page.wait_for_url("**/board", timeout=20_000)


def skip_resume(page: Page) -> None:
    page.click("#skipResume")
    page.wait_for_url("**/board", timeout=20_000)


def assert_still_signed_in(page: Page) -> dict[str, Any]:
    me = page.evaluate(
        """async () => {
          const res = await fetch("/api/auth/me", { credentials: "same-origin" });
          return { status: res.status, body: await res.json().catch(() => ({})) };
        }"""
    )
    assert me["status"] == 200, me
    assert me["body"].get("kind") == "admin" or me["body"].get("role") == "admin"
    return me["body"]


def api(
    page: Page,
    method: str,
    path: str,
    *,
    body: Any | None = None,
    token: str | None = None,
    content_type: str = "application/json",
    raw: bytes | None = None,
) -> dict[str, Any]:
    payload = {
        "method": method,
        "path": path,
        "token": token,
        "contentType": content_type,
        "jsonBody": body,
        "rawB64": None,
    }
    if raw is not None:
        import base64

        payload["jsonBody"] = None
        payload["rawB64"] = base64.b64encode(raw).decode("ascii")
    result = page.evaluate(
        """async (p) => {
          const headers = {};
          if (p.contentType) headers["Content-Type"] = p.contentType;
          if (p.token) headers["Authorization"] = "Bearer " + p.token;
          const csrfHit = document.cookie.split("; ").find((c) => c.startsWith("hub_csrf="));
          if (csrfHit) headers["X-CSRF"] = decodeURIComponent(csrfHit.split("=").slice(1).join("="));
          let body = undefined;
          if (p.rawB64) {
            const bin = atob(p.rawB64);
            const bytes = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
            body = bytes;
          } else if (p.jsonBody !== null && p.jsonBody !== undefined) {
            body = JSON.stringify(p.jsonBody);
          }
          const res = await fetch(p.path, { method: p.method, credentials: "same-origin", headers, body });
          const text = await res.text();
          let parsed = text;
          try { parsed = text ? JSON.parse(text) : {}; } catch (e) { parsed = text; }
          return { status: res.status, body: parsed };
        }""",
        payload,
    )
    return result


def request_json(
    request: APIRequestContext,
    method: str,
    path: str,
    *,
    token: str | None = None,
    data: Any | None = None,
    csrf: str | None = None,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if csrf:
        headers["X-CSRF"] = csrf
    kwargs: dict[str, Any] = {"headers": headers}
    if data is not None:
        headers["Content-Type"] = "application/json"
        kwargs["data"] = json.dumps(data)
    res = request.fetch(path, method=method, **kwargs)
    parsed: Any
    try:
        parsed = res.json()
    except Exception:
        parsed = res.text()
    return {"status": res.status, "body": parsed}


def create_invite(page: Page, track: str = "discovery") -> str:
    page.goto("/admin")
    expect(page.locator("#track")).to_be_visible()
    page.select_option("#track", track)
    page.click("form#form button[type='submit']")
    expect(page.locator("#created")).to_contain_text("join", timeout=15_000)
    url = page.locator("#url").inner_text().strip()
    assert "/join/" in url
    return url


def join_worker(page: Page, join_url: str, display_name: str) -> str:
    page.goto(join_url)
    expect(page.locator("#form")).to_be_visible(timeout=15_000)
    page.fill("#name", display_name)
    page.fill("#model", "e2e-model")
    page.fill("#harness", "playwright")
    page.fill("#bed", "cursor")
    page.fill("#provider", "e2e")
    page.fill("#capabilities", "browser, mcp")
    page.click("form#form button[type='submit']")
    expect(page.locator("#key")).to_contain_text("API key", timeout=15_000)
    match = re.search(r"(jh_(?:own|agt)_[A-Za-z0-9._-]+)", page.locator("#key").inner_text())
    assert match, page.locator("#key").inner_text()
    return match.group(1)
