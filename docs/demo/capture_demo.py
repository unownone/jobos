#!/usr/bin/env python3
"""Capture docs/demo screenshots + a short webm from the live Hub. No tokens in git."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
HUB = os.environ.get("HUB_URL", os.environ.get("BOARD_URL", "http://127.0.0.1:8787")).rstrip("/")
TOKEN = os.environ.get("BOARD_TOKEN_ADMIN", "")


def launch(p):
    kwargs: dict = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
    for candidate in (
        os.environ.get("CHROME_PATH"),
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
    ):
        if candidate and Path(candidate).is_file():
            kwargs["executable_path"] = candidate
            break
    try:
        return p.chromium.launch(**kwargs)
    except Exception:
        kwargs.pop("executable_path", None)
        return p.chromium.launch(**kwargs)


def fetch_health() -> dict:
    with urllib.request.urlopen(f"{HUB}/health", timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    video_dir = ROOT / "_video"
    video_dir.mkdir(exist_ok=True)
    health = fetch_health()

    with sync_playwright() as p:
        browser = launch(p)
        context = browser.new_context(
            viewport={"width": 1400, "height": 860},
            record_video_dir=str(video_dir),
            record_video_size={"width": 1400, "height": 860},
        )
        page = context.new_page()

        pretty = json.dumps(health, indent=2)
        page.set_content(
            f"""
            <html><body style="margin:0;background:#0e1218;color:#e7edf6;font:15px ui-sans-serif,system-ui">
              <main style="max-width:720px;margin:48px auto;padding:28px;background:#151b24;border:1px solid #2a3444;border-radius:16px">
                <p style="color:#8b97ab;text-transform:uppercase;letter-spacing:.08em;font-size:12px;margin:0 0 8px">GET /health</p>
                <h1 style="margin:0 0 16px">Job Hub is up</h1>
                <pre style="margin:0;padding:16px;background:#0e1218;border-radius:10px;overflow:auto;line-height:1.45">{pretty}</pre>
              </main>
            </body></html>
            """
        )
        page.wait_for_timeout(250)
        page.screenshot(path=str(ROOT / "01-health.png"), full_page=False)

        page.goto(f"{HUB}/login", wait_until="networkidle")
        page.wait_for_selector("h1")
        page.wait_for_timeout(250)
        page.screenshot(path=str(ROOT / "02-login.png"), full_page=False)

        page.goto(f"{HUB}/admin/signup", wait_until="networkidle")
        page.wait_for_selector("h1")
        page.wait_for_function("() => document.querySelector('h1')?.textContent?.includes('admin')")
        page.wait_for_timeout(250)
        page.screenshot(path=str(ROOT / "03-board.png"), full_page=False)

        onboard_html = ROOT.parents[1] / "board" / "app" / "static" / "onboarding.html"
        if onboard_html.is_file():
            page.goto(onboard_html.as_uri(), wait_until="domcontentloaded")
            page.wait_for_selector("h1")
            page.evaluate(
                """() => {
                  const who = document.getElementById("who");
                  const panel = document.getElementById("formPanel");
                  if (who) who.textContent = "Admin session required after signup. Fill a truthful profile — never Ada Example.";
                  if (panel) panel.hidden = false;
                }"""
            )
            page.wait_for_timeout(250)
            page.screenshot(path=str(ROOT / "04-onboarding.png"), full_page=False)
        else:
            page.goto(f"{HUB}/onboarding", wait_until="networkidle")
            page.wait_for_timeout(400)
            page.screenshot(path=str(ROOT / "04-onboarding.png"), full_page=False)

        if TOKEN:
            page.goto(f"{HUB}/", wait_until="networkidle")
            role = page.locator("#role")
            token_box = page.locator("#token")
            connect = page.locator("#connectBtn")
            if role.count() and token_box.count() and connect.count():
                role.select_option("admin")
                token_box.fill(TOKEN)
                connect.click()
                page.wait_for_timeout(800)
                page.screenshot(path=str(ROOT / "03-board.png"), full_page=False)

        context.close()
        browser.close()

        videos = list(video_dir.glob("*.webm"))
        dest = ROOT / "job_hub_feature_demo.webm"
        if videos:
            videos[0].replace(dest)
        for leftover in video_dir.glob("*"):
            leftover.unlink()
        try:
            video_dir.rmdir()
        except OSError:
            pass

    print("wrote", ROOT / "01-health.png")
    print("health", json.dumps(health))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
