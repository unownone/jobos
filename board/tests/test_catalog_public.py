"""Public CatalogQuery: approved shared skills + MCP names, no auth."""

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


def test_catalog_is_public_and_omits_local_and_bodies(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    seeded = client.post("/api/registry/seed", headers=h("maintenance"))
    assert seeded.status_code == 200, seeded.text

    local = client.post(
        "/api/registry/skills",
        headers=h("apply"),
        json={
            "slug": "secret-local-draft",
            "name": "Secret local draft",
            "role": "apply",
            "tags": ["apply"],
            "body": "must not appear on the public catalog",
        },
    )
    assert local.status_code == 200, local.text

    unauth = client.get("/api/registry/catalog")
    assert unauth.status_code == 200, unauth.text
    body = unauth.json()
    assert "Always use registry" in body["note"]
    slugs = {row["slug"] for row in body["skills"]}
    assert "secret-local-draft" not in slugs
    assert body["mcp_count"] >= 1
    assert any(row["id"] == "exa" for row in body["mcps"])
    for row in body["skills"]:
        assert "body" not in row
        assert row["scope"] == "shared"
        assert row["status"] == "approved"
        assert "must not appear" not in str(row)
    dumped = unauth.text
    assert "must not appear on the public catalog" not in dumped
    assert "jh_agt_" not in dumped

    tagged = client.get("/api/registry/catalog", params={"tag": "source"})
    assert tagged.status_code == 200
    for row in tagged.json()["skills"]:
        assert "source" in [str(t).lower() for t in row["tags"]]


def test_authed_skills_list_still_requires_credentials(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    denied = client.get("/api/registry/skills")
    assert denied.status_code in {401, 403}
