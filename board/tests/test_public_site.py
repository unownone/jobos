"""Public marketing surfaces: landing and get-started."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        board_dir=tmp_path,
        db_path=tmp_path / "board.db",
        host="127.0.0.1",
        port=8787,
        tokens={"admin": "test-token-admin-not-real"},
        blob_adapter="memory",
        queue_adapter="memory",
        blob_root=tmp_path / "blobs",
    )


def test_landing_explains_harness_and_points_home(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    res = client.get("/")
    assert res.status_code == 200
    text = res.text
    assert "jobOS" in text
    assert "Find jobs with a harness" in text
    assert "https://github.com/unownone/jobos" in text
    assert "https://github.com/unownone" in text
    assert "made by" in text
    assert "unownone" in text
    assert "Never Easy Apply" in text or "never Easy Apply" in text
    assert "Discovery" in text
    assert "Outreach" in text
    assert "Maintainer" in text
    assert "/static/theme.css" in text
    assert "/static/app/" in text
    assert "/static/hub.css" not in text


def test_get_started_is_public_and_honest_about_blockers(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    res = client.get("/start")
    assert res.status_code == 200
    text = res.text
    assert "Get started" in text
    assert "candidate_required" in text
    assert "Deployed agents" in text
    assert "not shipped" in text.lower() or "Coming soon" in text
    assert "https://github.com/unownone/jobos" in text
    assert "/static/theme.css" in text
    assert "/static/app/" in text


def test_public_css_and_fonts_are_reachable(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    css = client.get("/static/public.css")
    assert css.status_code == 200
    assert 'url("/static/theme.css")' in css.text
    theme = client.get("/static/theme.css")
    assert theme.status_code == 200
    assert "--amber" in theme.text
    assert "--chassis: #0b1220" in theme.text
    assert "Big Shoulders Display" in theme.text
    font = client.get("/static/fonts/red-hat-text-400.woff2")
    assert font.status_code == 200
    js = client.get("/static/public.js")
    assert js.status_code == 200


def test_public_js_rewrites_login_when_session_exists() -> None:
    js = Path(__file__).resolve().parents[1] / "app" / "static" / "public.js"
    text = js.read_text(encoding="utf-8")
    assert "/api/auth/me" in text
    assert "Open board" in text


def test_hub_and_public_share_one_theme_file() -> None:
    static = Path(__file__).resolve().parents[1] / "app" / "static"
    theme = (static / "theme.css").read_text(encoding="utf-8")
    hub = (static / "hub.css").read_text(encoding="utf-8")
    public = (static / "public.css").read_text(encoding="utf-8")
    assert "@import url(\"/static/theme.css\")" in hub
    assert "@import url(\"/static/theme.css\")" in public
    assert "--chassis: #0b1220" in theme
    assert "--amber: #e0992d" in theme
    assert "--navy: var(--amber)" in theme
    assert "--paper: var(--chassis)" in theme
    assert "--chassis: #" not in hub
    assert "--paper: #ebe6dc" not in hub
    assert "--navy: #1e3a5f" not in hub
    assert "--chassis: #" not in public

