"""Hub auth: invites, owners, agent keys, session login, compat tokens."""

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
    )


@pytest.fixture()
def hub(tmp_path: Path) -> tuple[TestClient, Settings]:
    settings = _settings(tmp_path)
    return TestClient(create_app(settings)), settings


def h(role: str, actor: str = "pytest") -> dict[str, str]:
    return {"X-Role": role, "X-Token": TOKENS[role], "X-Actor": actor}


def csrf_headers(client: TestClient, extra: dict[str, str] | None = None) -> dict[str, str]:
    csrf = client.cookies.get("hub_csrf") or ""
    headers = {"X-CSRF": csrf, "Content-Type": "application/json"}
    if extra:
        headers.update(extra)
    return headers


def bootstrap_admin(client: TestClient) -> None:
    token = client.app.state.bootstrap_token
    res = client.post(
        "/api/auth/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "owner@example.test", "password": "correct-horse"},
    )
    assert res.status_code == 200, res.text
    assert "hub_session" in client.cookies


def test_bootstrap_still_one_time(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    token = client.app.state.bootstrap_token
    second = client.post(
        "/api/auth/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "other@example.test", "password": "correct-horse"},
    )
    assert second.status_code == 403


def test_session_login_logout_me(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    client.cookies.clear()
    denied = client.get("/api/auth/me")
    assert denied.status_code == 401
    login = client.post(
        "/api/auth/login",
        json={"email": "owner@example.test", "password": "correct-horse"},
    )
    assert login.status_code == 200, login.text
    assert "hub_session" in login.cookies
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["kind"] == "admin"
    assert body["role"] == "admin"
    assert body["track"] is None
    assert body["user"]["email"] == "owner@example.test"
    logout = client.post("/api/auth/logout", headers=csrf_headers(client))
    assert logout.status_code == 200
    after = client.get("/api/auth/me")
    assert after.status_code == 401


def test_invite_create_join_owner_then_agent(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    created = client.post(
        "/api/invites",
        headers=csrf_headers(client),
        json={
            "track": "discovery",
            "max_redemptions": 8,
            "ttl_hours": 72,
            "mode": "owner_then_agents",
        },
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    invite_id = payload["invite"]["id"]
    secret = payload["secret"]
    assert payload["join_url"] == f"https://hub.example.test/join/{invite_id}?s={secret}"
    listed = client.get("/api/invites")
    assert listed.status_code == 200
    assert "secret" not in listed.json()["invites"][0]
    assert listed.json()["invites"][0]["max_redemptions"] == 8

    join_page = client.get(f"/join/{invite_id}?s={secret}")
    assert join_page.status_code == 200
    assert "Join" in join_page.text

    preview = client.get(f"/api/join/{invite_id}?s={secret}")
    assert preview.status_code == 200
    info = preview.json()
    assert info["track"] == "discovery"
    assert info["join"]["url"] == "/api/auth/join"
    assert info["candidate"]["present"] is False
    assert "model" in info["metadata_known_keys"]

    first = client.post(
        "/api/auth/join",
        json={
            "invite_id": invite_id,
            "s": secret,
            "display_name": "discovery-owner",
            "metadata": {
                "model": "grok-4",
                "harness": "cursor-cloud",
                "bed": "cursor",
                "provider": "xai",
                "capabilities": ["browser", "mcp"],
                "custom_flag": True,
            },
        },
    )
    assert first.status_code == 200, first.text
    owner_body = first.json()
    assert owner_body["kind"] == "owner"
    assert owner_body["track"] == "discovery"
    assert owner_body["api_key"].startswith("jh_own_discovery_")
    assert owner_body["user"]["metadata"]["model"] == "grok-4"
    assert owner_body["user"]["metadata"]["extra"]["custom_flag"] is True
    owner_key = owner_body["api_key"]

    second = client.post(
        "/api/auth/join",
        json={
            "invite_id": invite_id,
            "s": secret,
            "display_name": "discovery-agent-1",
            "model": "claude",
            "harness": "claude-code",
            "bed": "cli",
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["kind"] == "agent"
    assert second.json()["api_key"].startswith("jh_agt_")
    agent_key = second.json()["api_key"]

    jobs = client.get("/api/jobs", headers={"Authorization": f"Bearer {agent_key}"})
    assert jobs.status_code == 200
    me_agent = client.get("/api/auth/me", headers={"X-Hub-Key": agent_key})
    assert me_agent.status_code == 200
    assert me_agent.json()["kind"] == "agent"
    assert me_agent.json()["role"] == "discovery"
    assert "api_key" not in me_agent.json()
    assert me_agent.json()["user"]["metadata"]["harness"] == "claude-code"

    mint = client.post(
        "/api/agents",
        headers={"Authorization": f"Bearer {owner_key}"},
        json={"display_name": "discovery-agent-2", "metadata": {"model": "gpt"}},
    )
    assert mint.status_code == 200, mint.text
    assert mint.json()["kind"] == "agent"
    minted_key = mint.json()["api_key"]
    assert minted_key.startswith("jh_agt_")

    forbidden = client.post(
        "/api/agents",
        headers={"Authorization": f"Bearer {agent_key}"},
        json={"display_name": "should-fail"},
    )
    assert forbidden.status_code == 403

    listed_jobs = client.get("/api/jobs", headers=h("discovery"))
    assert listed_jobs.status_code == 200


def test_one_owner_per_track(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    first_inv = client.post(
        "/api/invites",
        headers=csrf_headers(client),
        json={"track": "outreach", "mode": "owner_only", "max_redemptions": 2},
    ).json()
    second_inv = client.post(
        "/api/invites",
        headers=csrf_headers(client),
        json={"track": "outreach", "mode": "owner_then_agents", "max_redemptions": 2},
    ).json()
    ok = client.post(
        "/api/auth/join",
        json={
            "invite_id": first_inv["invite"]["id"],
            "s": first_inv["secret"],
            "display_name": "outreach-owner",
        },
    )
    assert ok.status_code == 200
    as_agent = client.post(
        "/api/auth/join",
        json={
            "invite_id": second_inv["invite"]["id"],
            "s": second_inv["secret"],
            "display_name": "outreach-agent",
        },
    )
    assert as_agent.status_code == 200
    assert as_agent.json()["kind"] == "agent"
    owner_only_again = client.post(
        "/api/invites",
        headers=csrf_headers(client),
        json={"track": "outreach", "mode": "owner_only", "max_redemptions": 1},
    ).json()
    denied = client.post(
        "/api/auth/join",
        json={
            "invite_id": owner_only_again["invite"]["id"],
            "s": owner_only_again["secret"],
            "display_name": "outreach-owner-2",
        },
    )
    assert denied.status_code == 403
    flagged = client.post(
        "/api/invites",
        headers=csrf_headers(client),
        json={
            "track": "outreach",
            "mode": "owner_only",
            "max_redemptions": 1,
            "allow_multiple_owners": True,
        },
    ).json()
    extra = client.post(
        "/api/auth/join",
        json={
            "invite_id": flagged["invite"]["id"],
            "s": flagged["secret"],
            "display_name": "outreach-owner-2",
        },
    )
    assert extra.status_code == 200
    assert extra.json()["kind"] == "owner"


def test_expired_and_revoked_invite(hub: tuple[TestClient, Settings]) -> None:
    client, settings = hub
    bootstrap_admin(client)
    created = client.post(
        "/api/invites",
        headers=csrf_headers(client),
        json={"track": "maintenance", "max_redemptions": 2},
    ).json()
    invite_id = created["invite"]["id"]
    secret = created["secret"]
    client.app.state.db.expire_invite(invite_id, "2000-01-01T00:00:00Z")
    gone = client.post(
        "/api/auth/join",
        json={"invite_id": invite_id, "s": secret, "display_name": "too-late"},
    )
    assert gone.status_code == 410
    preview = client.get(f"/api/join/{invite_id}?s={secret}")
    assert preview.status_code == 410

    fresh = client.post(
        "/api/invites",
        headers=csrf_headers(client),
        json={"track": "maintenance", "max_redemptions": 2},
    ).json()
    revoked = client.post(
        f"/api/invites/{fresh['invite']['id']}/revoke",
        headers=csrf_headers(client),
    )
    assert revoked.status_code == 200
    blocked = client.post(
        "/api/auth/join",
        json={
            "invite_id": fresh["invite"]["id"],
            "s": fresh["secret"],
            "display_name": "nope",
        },
    )
    assert blocked.status_code == 403


def test_application_key_cannot_create_job(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    created = client.post(
        "/api/invites",
        headers=csrf_headers(client),
        json={"track": "application", "max_redemptions": 2},
    ).json()
    joined = client.post(
        "/api/auth/join",
        json={
            "invite_id": created["invite"]["id"],
            "s": created["secret"],
            "display_name": "apply-owner",
        },
    )
    assert joined.status_code == 200
    key = joined.json()["api_key"]
    assert key.startswith("jh_own_application_")
    res = client.post(
        "/api/jobs",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "id": "remoteok__hub-auth",
            "company": "Acme",
            "title": "Staff Engineer",
            "apply_url": "https://jobs.example.com/staff-auth",
            "sources": ["remoteok"],
        },
    )
    assert res.status_code == 403
    listed = client.get("/api/jobs", headers={"X-Hub-Key": key})
    assert listed.status_code == 200


def test_compat_tokens_still_work(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    created = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={
            "id": "remoteok__compat-auth",
            "company": "Acme",
            "title": "Staff Engineer",
            "apply_url": "https://jobs.example.com/staff-compat-auth",
            "sources": ["remoteok"],
            "status": "apply_ready",
            "apply_packet": {"url": "https://jobs.example.com/staff-compat-auth", "steps": ["Open"]},
        },
    )
    assert created.status_code == 201, created.text
    listed = client.get("/api/jobs", headers=h("apply"))
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    who = client.get("/api/whoami", headers=h("apply"))
    assert who.json()["compat"] is True
    assert who.json()["role"] == "apply"


def test_key_rotation_and_disable(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    created = client.post(
        "/api/invites",
        headers=csrf_headers(client),
        json={"track": "discovery", "max_redemptions": 3},
    ).json()
    owner = client.post(
        "/api/auth/join",
        json={
            "invite_id": created["invite"]["id"],
            "s": created["secret"],
            "display_name": "rot-owner",
        },
    ).json()
    minted = client.post(
        "/api/agents",
        headers={"Authorization": f"Bearer {owner['api_key']}"},
        json={"display_name": "rot-agent"},
    ).json()
    old_key = minted["api_key"]
    user_id = minted["user"]["id"]
    rotated = client.post(
        f"/api/agents/{user_id}/rotate_key",
        headers={"Authorization": f"Bearer {owner['api_key']}"},
    )
    assert rotated.status_code == 200
    new_key = rotated.json()["api_key"]
    assert new_key != old_key
    assert client.get("/api/jobs", headers={"Authorization": f"Bearer {old_key}"}).status_code == 401
    assert client.get("/api/jobs", headers={"Authorization": f"Bearer {new_key}"}).status_code == 200
    disabled = client.post(
        f"/api/agents/{user_id}/disable",
        headers={"Authorization": f"Bearer {owner['api_key']}"},
    )
    assert disabled.status_code == 200
    assert client.get("/api/jobs", headers={"Authorization": f"Bearer {new_key}"}).status_code == 401


def test_login_pages_exist(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    assert client.get("/login").status_code == 200
    assert "Admin login" in client.get("/login").text
    assert client.get("/admin/invites").status_code == 200
