"""Candidate public slice revision bumps and is not cached."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.constants import ROLES
from app.main import create_app
from app.settings import Settings

TOKENS = {role: f"test-token-{role}-not-real" for role in ROLES}


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        board_dir=tmp_path,
        db_path=tmp_path / "board.db",
        host="127.0.0.1",
        port=8787,
        tokens=dict(TOKENS),
        public_url="https://hub.example.test",
        bootstrap_token="",
        env_path=tmp_path / ".env",
        tokens_json_path=tmp_path / "tokens.local.json",
    )


def h(role: str) -> dict[str, str]:
    return {"X-Role": role, "X-Token": TOKENS[role], "X-Actor": "pytest"}


def test_public_candidate_revision_bumps_and_no_store(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    first = client.get("/api/candidate/public", headers=h("discovery"))
    assert first.status_code == 200, first.text
    assert first.headers.get("cache-control") == "no-store"
    body = first.json()
    assert body["present"] is True
    rev1 = body["revision"]
    assert rev1
    assert first.headers.get("etag") == f'"{rev1}"'

    path = tmp_path / "profiles" / "candidate.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("Staff Software Engineer", "Principal Engineer"), encoding="utf-8")

    second = client.get("/api/candidate/public", headers=h("apply"))
    assert second.status_code == 200
    body2 = second.json()
    assert body2["revision"] != rev1
    titles = (body2.get("target") or {}).get("titles") or []
    assert "Principal Engineer" in titles
    heartbeat = client.post(
        "/api/presence/heartbeat",
        headers=h("discovery"),
        json={"status_hint": "logged_in"},
    )
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["candidate_revision"] == body2["revision"]


def test_admin_data_page_and_brand_assets(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    denied = client.get("/admin/data")
    assert denied.status_code in {401, 302}
    page = client.get("/admin/data", headers=h("admin"))
    assert page.status_code == 200
    assert "jobOS data" in page.text
    mascot = client.get("/brand/mascot.png")
    assert mascot.status_code == 200
    assert mascot.headers.get("content-type", "").startswith("image/")
    icon = client.get("/favicon.ico")
    assert icon.status_code == 200
