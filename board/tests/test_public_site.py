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
    assert "/start" in text
    assert "/static/public.css" in text
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
    assert "/static/public.css" in text


def test_public_css_and_fonts_are_reachable(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    css = client.get("/static/public.css")
    assert css.status_code == 200
    assert "--amber" in css.text
    assert "Big Shoulders Display" in css.text
    font = client.get("/static/fonts/red-hat-text-400.woff2")
    assert font.status_code == 200
    js = client.get("/static/public.js")
    assert js.status_code == 200
