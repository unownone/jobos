"""Candidate onboarding is mandatory before Hub work."""

from __future__ import annotations

from pathlib import Path

import pytest
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
        packs_dir=tmp_path / "packs",
    )


@pytest.fixture()
def hub(tmp_path: Path) -> tuple[TestClient, Settings]:
    return TestClient(create_app(_settings(tmp_path))), _settings(tmp_path)


def h(role: str) -> dict[str, str]:
    return {"X-Role": role, "X-Token": TOKENS[role], "X-Actor": "pytest"}


def csrf_headers(client: TestClient) -> dict[str, str]:
    csrf = client.cookies.get("hub_csrf") or ""
    return {"X-CSRF": csrf, "Content-Type": "application/json"}


def bootstrap_admin(client: TestClient) -> None:
    token = client.app.state.bootstrap_token
    res = client.post(
        "/api/auth/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "owner@example.test", "password": "correct-horse"},
    )
    assert res.status_code == 200, res.text


@pytest.mark.no_candidate
def test_health_points_at_onboarding(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    health = client.get("/health").json()
    assert health["candidate_onboarded"] is False
    assert health["next_step"] in {"signup", "onboarding"}
    denied = client.get("/onboarding")
    assert denied.status_code == 401
    bootstrap_admin(client)
    page = client.get("/onboarding")
    assert page.status_code == 200
    assert "Candidate onboarding" in page.text


@pytest.mark.no_candidate
def test_jobs_and_invites_blocked_until_profile(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    blocked = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={"company": "Acme", "title": "Staff", "id": "remoteok__blocked"},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["code"] == "candidate_required"

    bootstrap_admin(client)
    invites = client.post(
        "/api/invites",
        headers=csrf_headers(client),
        json={"track": "discovery", "max_redemptions": 2},
    )
    assert invites.status_code == 409
    assert invites.json()["detail"]["onboarding_url"] == "/onboarding"


@pytest.mark.no_candidate
def test_example_profile_rejected_then_real_profile_unlocks(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    example = client.put(
        "/api/candidate",
        headers=csrf_headers(client),
        json={
            "identity": {"full_name": "Ada Example", "email": "ada@example.com"},
            "target": {"titles": ["Staff"], "locations": ["Remote"]},
        },
    )
    assert example.status_code == 422, example.text

    saved = client.put(
        "/api/candidate",
        headers=csrf_headers(client),
        json={
            "identity": {
                "full_name": "Jordan Lee",
                "email": "jordan@example.test",
                "location": "Remote",
                "work_authorization": "US citizen",
            },
            "target": {
                "titles": ["Staff Software Engineer"],
                "locations": ["Remote"],
                "deal_breakers": ["Unpaid trials"],
            },
            "proof": {"headline": "Ships backends", "highlights": ["Owns a service"]},
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["onboarded"] is True
    health = client.get("/health").json()
    assert health["candidate_onboarded"] is True
    created = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={
            "id": "remoteok__after-onboard",
            "company": "Acme",
            "title": "Staff Engineer",
            "status": "discovered",
        },
    )
    assert created.status_code == 201, created.text


def test_onboarding_page_and_status_with_fixture(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    assert client.get("/api/candidate/status").status_code == 401
    status = client.get("/api/candidate/status", headers=h("admin"))
    assert status.status_code == 200
    assert status.json()["onboarded"] is True
    assert client.get("/onboarding", headers=h("admin")).status_code == 200
    assert client.get("/.well-known/agent-card.json").status_code == 200
    card = client.get("/.well-known/agent-card.json", headers={"Origin": "https://other-agent.example"})
    assert card.headers.get("access-control-allow-origin") == "*"
