"""Hub serves llms.txt / agents.txt as public text/plain."""

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
        repo_root=Path(__file__).resolve().parents[2],
    )


def test_briefing_routes_are_public_text_plain(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    for path in (
        "/llms.txt",
        "/agents.txt",
        "/.well-known/llms.txt",
        "/.well-known/agents.txt",
    ):
        res = client.get(path)
        assert res.status_code == 200, path
        assert res.headers.get("content-type", "").startswith("text/plain")
        assert res.headers.get("cache-control") == "no-store"
        assert "{{HUB_URL}}" not in res.text
        assert "https://hub.example.test" in res.text
        assert "jh_boot_" not in res.text
        assert "jh_agt_" not in res.text or "jh_agt_…" in res.text


def test_llms_txt_points_at_registry_and_health(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    text = client.get("/llms.txt").text
    assert "/health" in text
    assert "/api/onboarding" in text
    assert "/api/registry/catalog" in text
    assert "/api/registry/skills" in text
    assert "/api/registry/seed" in text
    assert "/api/memory/recall" in text
    assert "/api/queue/claim" in text
    assert "/api/candidate/public" in text
    assert "coming soon" in text.lower()


def test_meta_lists_coming_soon_and_briefing(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    meta = client.get(
        "/api/meta",
        headers={"X-Role": "admin", "X-Token": TOKENS["admin"]},
    )
    assert meta.status_code == 200, meta.text
    body = meta.json()
    ids = {row["id"] for row in body["coming_soon_roles"]}
    assert ids == {"review", "resume"}
    assert all(row["status"] == "coming_soon" for row in body["coming_soon_roles"])
    assert body["briefing"]["llms_txt"] == "/llms.txt"
    assert body["briefing"]["agents_txt"] == "/agents.txt"
