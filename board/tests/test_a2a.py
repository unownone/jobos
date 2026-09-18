"""A2A JSON-RPC + Agent Cards. Cross-agent plane beyond this repo."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

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


def hub(tmp_path: Path) -> TestClient:
    return TestClient(create_app(_settings(tmp_path)))


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


def invite_join(client: TestClient, track: str, display_name: str) -> dict:
    created = client.post(
        "/api/invites",
        headers=csrf_headers(client),
        json={"track": track, "max_redemptions": 8, "mode": "agents_only"},
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    joined = client.post(
        "/api/auth/join",
        json={
            "invite_id": payload["invite"]["id"],
            "s": payload["secret"],
            "display_name": display_name,
        },
    )
    assert joined.status_code == 200, joined.text
    return joined.json()


def test_agent_card_is_public(tmp_path: Path) -> None:
    client = hub(tmp_path)
    card = client.get("/.well-known/agent-card.json")
    assert card.status_code == 200, card.text
    body = card.json()
    assert body["protocolVersion"] == "0.3.0"
    assert body["preferredTransport"] == "JSONRPC"
    assert body["url"].endswith("/a2a")
    ids = {s["id"] for s in body["skills"]}
    assert "hub.discovery" in ids
    assert "hub.handoff" in ids
    alias = client.get("/.well-known/agent.json")
    assert alias.status_code == 200
    track = client.get("/a2a/application/agent-card.json")
    assert track.status_code == 200
    assert track.json()["url"].endswith("/a2a/application")
    assert client.get("/a2a/not-a-track/agent-card.json").status_code == 404


def test_message_send_without_auth_is_auth_required(tmp_path: Path) -> None:
    client = hub(tmp_path)
    res = client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "messageId": str(uuid4()),
                    "parts": [{"kind": "text", "text": "handoff Acme packet"}],
                }
            },
        },
    )
    assert res.status_code == 200, res.text
    result = res.json()["result"]
    assert result["kind"] == "task"
    assert result["status"]["state"] == "auth-required"


def test_a2a_handoff_lands_in_track_inbox(tmp_path: Path) -> None:
    client = hub(tmp_path)
    bootstrap_admin(client)
    discovery = invite_join(client, "discovery", "disc-a2a")
    apply_user = invite_join(client, "application", "apply-a2a")
    sent = client.post(
        "/a2a",
        headers={"Authorization": f"Bearer {discovery['api_key']}"},
        json={
            "jsonrpc": "2.0",
            "id": "rpc-9",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "messageId": str(uuid4()),
                    "parts": [
                        {"kind": "text", "text": "packet ready for Acme staff"},
                        {
                            "kind": "data",
                            "data": {
                                "type": "handoff",
                                "to_track": "apply",
                                "job_id": "remoteok__acme-a2a",
                            },
                        },
                    ],
                }
            },
        },
    )
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert "error" not in body
    task = body["result"]
    assert task["status"]["state"] == "completed"
    assert task["artifacts"]
    inbox = client.get(
        "/api/messages",
        headers={"Authorization": f"Bearer {apply_user['api_key']}"},
        params={"unread": "1"},
    )
    assert inbox.status_code == 200
    assert inbox.json()["count"] == 1
    assert inbox.json()["messages"][0]["type"] == "handoff"
    fetched = client.post(
        "/a2a",
        headers={"Authorization": f"Bearer {discovery['api_key']}"},
        json={"jsonrpc": "2.0", "id": "2", "method": "tasks/get", "params": {"id": task["id"]}},
    )
    assert fetched.json()["result"]["id"] == task["id"]


def test_track_endpoint_defaults_destination(tmp_path: Path) -> None:
    client = hub(tmp_path)
    bootstrap_admin(client)
    discovery = invite_join(client, "discovery", "disc-a2a-track")
    outreach = invite_join(client, "outreach", "out-a2a")
    sent = client.post(
        "/a2a/outreach",
        headers={"Authorization": f"Bearer {discovery['api_key']}"},
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "messageId": "m1",
                    "parts": [{"kind": "text", "text": "need a hiring manager name"}],
                }
            },
        },
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["result"]["status"]["state"] == "completed"
    inbox = client.get(
        "/api/messages",
        headers={"Authorization": f"Bearer {outreach['api_key']}"},
    )
    assert inbox.json()["count"] == 1


def test_directory_lists_local_track_agents(tmp_path: Path) -> None:
    client = hub(tmp_path)
    listing = client.get("/api/a2a/directory", headers=h("admin"))
    assert listing.status_code == 200, listing.text
    body = listing.json()
    urls = {row["card_url"] for row in body["local"]}
    assert "https://hub.example.test/.well-known/agent-card.json" in urls
    assert body["protocolVersion"] == "0.3.0"


def test_unknown_method(tmp_path: Path) -> None:
    client = hub(tmp_path)
    res = client.post(
        "/a2a",
        headers=h("admin"),
        json={"jsonrpc": "2.0", "id": 1, "method": "nope/send", "params": {}},
    )
    assert res.json()["error"]["code"] == -32601


@pytest.mark.no_candidate
def test_a2a_send_requires_candidate(tmp_path: Path) -> None:
    client = hub(tmp_path)
    res = client.post(
        "/a2a",
        headers=h("admin"),
        json={
            "jsonrpc": "2.0",
            "id": "gate",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "messageId": "m-gate",
                    "parts": [{"kind": "text", "text": "handoff before profile exists"}],
                }
            },
        },
    )
    assert res.status_code == 200, res.text
    err = res.json()["error"]
    assert err["code"] == -32090
    assert err["data"]["onboarding_url"] == "/onboarding"
