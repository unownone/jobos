"""Playwright helper for board/scripts/capture_readme_shots.sh. Do not commit tokens."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    from playwright.sync_api import sync_playwright

    url = os.environ["BOARD_URL"].rstrip("/")
    token = os.environ["BOARD_TOKEN_ADMIN"]
    dash_path = Path(os.environ["SHOT_DASH"])
    filters_path = Path(os.environ["SHOT_FILTERS"])
    detail_path = Path(os.environ["SHOT_DETAIL"])
    detail_id = os.environ.get("SHOT_DETAIL_ID", "")
    for path in (dash_path, filters_path, detail_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        launch_kwargs: dict = {"headless": True}
        for candidate in (
            os.environ.get("CHROME_PATH"),
            "/usr/local/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/opt/google/chrome/chrome",
        ):
            if candidate and Path(candidate).is_file():
                launch_kwargs["executable_path"] = candidate
                break
        try:
            browser = p.chromium.launch(**launch_kwargs)
        except Exception:
            browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 860})
        page.goto(url, wait_until="networkidle")
        page.select_option("#role", "admin")
        page.fill("#token", token)
        page.click("#connectBtn")
        page.wait_for_selector("#connStatus.on", timeout=10000)
        page.wait_for_selector("#list table, #list .empty", timeout=10000)
        page.wait_for_timeout(400)
        page.screenshot(path=str(dash_path), full_page=False)

        page.click("#statusBtn")
        page.wait_for_selector("#statusMenu:not([hidden])")
        page.wait_for_timeout(200)
        page.screenshot(path=str(filters_path), full_page=False)
        page.keyboard.press("Escape")
        page.evaluate("document.getElementById('statusMenu').hidden = true")

        row = page.locator(f'#list tbody tr[data-id="{detail_id}"]') if detail_id else page.locator("#list tbody tr").first
        if row.count() == 0:
            row = page.locator("#list tbody tr").first
        if row.count():
            row.click()
            page.wait_for_selector("#saveBtn")
            page.wait_for_timeout(300)
            page.screenshot(path=str(detail_path), full_page=False)
        browser.close()
    print(f"screenshots: {dash_path} {filters_path} {detail_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ImportError:
        print("playwright is not installed. The shell wrapper uses: uv run --with playwright", file=sys.stderr)
        raise
