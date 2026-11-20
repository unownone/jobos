"""OAuth into /mcp, session lanes, and the older job API still listing."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.constants import ROLES
from app.main import create_app
from app.settings import Settings

TOKENS = {role: f"test-token-{role}-not-real" for role in ROLES}
REDIRECT = "http://127.0.0.1:9/callback"


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


def _pkce() -> tuple[str, str]:
    verifier = "a" * 64
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _csrf(client: TestClient) -> dict[str, str]:
    return {
        "X-CSRF": client.cookies.get("hub_csrf") or "",
        "Content-Type": "application/json",
    }


def _tool(client: TestClient, token: str, session_id: str, name: str, arguments: dict | None = None, msg_id: int = 3) -> dict:
    res = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token}", "Mcp-Session-Id": session_id},
        json={
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "error" not in body, body
    result = body["result"]
    text = result["content"][0]["text"]
    payload = json.loads(text)
    assert result.get("isError") is not True, payload
    return payload


def test_mcp_oauth_lanes_loops_and_legacy_jobs(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    denied = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert denied.status_code == 401
    assert "oauth-protected-resource" in denied.headers["www-authenticate"]

    meta = client.get("/.well-known/oauth-protected-resource/mcp")
    assert meta.status_code == 200
    assert meta.json()["resource"] == "https://hub.example.test/mcp"
    server = client.get("/.well-known/oauth-authorization-server")
    assert server.json()["registration_endpoint"].endswith("/oauth/register")
    assert "S256" in server.json()["code_challenge_methods_supported"]

    registered = client.post(
        "/oauth/register",
        json={
            "client_name": "Test AI",
            "redirect_uris": [REDIRECT],
            "token_endpoint_auth_method": "none",
        },
    )
    assert registered.status_code == 201, registered.text
    client_id = registered.json()["client_id"]
    verifier, challenge = _pkce()
    anon = client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "s1",
        },
        follow_redirects=False,
    )
    assert anon.status_code == 302
    assert anon.headers["location"].startswith("/login?next=/oauth/authorize")

    token = client.app.state.bootstrap_token
    boot = client.post(
        "/api/auth/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "owner@example.test", "password": "correct-horse"},
    )
    assert boot.status_code == 200, boot.text

    page = client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "s1",
        },
    )
    assert page.status_code == 200
    assert "Approve" in page.text
    assert "Test AI" in page.text

    approved = client.post(
        "/oauth/authorize",
        headers=_csrf(client),
        json={
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "s1",
            "decision": "approve",
        },
    )
    assert approved.status_code == 200, approved.text
    parsed = urlparse(approved.json()["redirect"])
    code = parse_qs(parsed.query)["code"][0]
    assert parse_qs(parsed.query)["state"][0] == "s1"

    issued = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        },
    )
    assert issued.status_code == 200, issued.text
    access = issued.json()["access_token"]
    refresh = issued.json()["refresh_token"]
    assert issued.json()["expires_in"] >= 3600

    init = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test-ai", "version": "0"},
            },
        },
    )
    assert init.status_code == 200, init.text
    session_id = init.headers["mcp-session-id"]
    assert "not stuck in a single lane" in init.json()["result"]["instructions"]
    noted = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {access}", "Mcp-Session-Id": session_id},
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert noted.status_code == 202

    listed = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {access}", "Mcp-Session-Id": session_id},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    names = {tool["name"] for tool in listed.json()["result"]["tools"]}
    assert {"get_started", "set_session_lanes", "evaluate_lane", "start_loop", "next_loop", "read_skill"} <= names

    started = _tool(client, access, session_id, "get_started")
    assert started["prompts"] == ["get started", "find jobs", "apply jobs", "outreach jobs"]
    assert started["session"]["lanes"] == []
    asked = _tool(client, access, session_id, "ask_session_lanes", msg_id=4)
    assert "Which lanes" in asked["ask_human"]

    blocked = _tool(client, access, session_id, "evaluate_lane", {"lane": "find"}, msg_id=5)
    assert blocked["can"] is False

    chosen = _tool(
        client,
        access,
        session_id,
        "set_session_lanes",
        {"lanes": ["find", "apply", "outreach"]},
        msg_id=6,
    )
    assert chosen["session"]["lanes"] == ["find", "apply", "outreach"]
    reported = _tool(
        client,
        access,
        session_id,
        "report_capabilities",
        {"browser": True, "email": False},
        msg_id=7,
    )
    assert reported["checks"]["find"]["can"] is True
    assert reported["checks"]["apply"]["can"] is True
    assert reported["checks"]["outreach"]["can"] is False

    skill = _tool(client, access, session_id, "read_skill", {"slug": "job-discovery"}, msg_id=8)
    assert "Capability gate" in skill["body"]
    assert skill["needs"] == ["browser"]

    loop = _tool(client, access, session_id, "start_loop", {"lane": "find", "goal": "first pass"}, msg_id=9)
    assert loop["continue"] is True
    assert loop["lane"] == "find"
    nxt = _tool(client, access, session_id, "next_loop", {"loop_id": loop["loop_id"]}, msg_id=10)
    assert nxt["continue"] is True

    created = _tool(
        client,
        access,
        session_id,
        "create_job",
        {"company": "Acme", "title": "Staff Engineer", "apply_url": "https://jobs.example.test/acme-staff"},
        msg_id=11,
    )
    assert created["job"]["company"] == "Acme"

    jobs = client.get("/api/jobs")
    assert jobs.status_code == 200, jobs.text
    assert any(row["company"] == "Acme" for row in jobs.json()["jobs"])

    legacy = client.get(
        "/api/jobs",
        headers={"X-Role": "discovery", "X-Token": TOKENS["discovery"], "X-Actor": "legacy"},
    )
    assert legacy.status_code == 200, legacy.text

    steer = client.post(
        "/api/agent/steers",
        headers=_csrf(client),
        json={"body": "Prefer staff backend roles this week.", "session_id": session_id},
    )
    assert steer.status_code == 200, steer.text
    steers = _tool(client, access, session_id, "read_steers", msg_id=12)
    assert any("staff backend" in row["body"] for row in steers["steers"])

    page = client.get("/connect")
    assert page.status_code == 200
    assert 'id="mcpUrl"' in page.text
    assert "get started" in page.text

    status = client.get("/api/agent/status")
    assert status.status_code == 200
    body = status.json()
    assert body["mcp_url"] == "https://hub.example.test/mcp"
    assert body["connected"] is True
    assert body["grants"][0]["session"]["lanes"] == ["find", "apply", "outreach"]
    assert body["grants"][0]["session"]["capabilities"]["browser"] is True

    refreshed = client.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": refresh},
    )
    assert refreshed.status_code == 200, refreshed.text
    new_access = refreshed.json()["access_token"]
    assert new_access != access
    reused = client.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": refresh},
    )
    assert reused.status_code == 400
    dead = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {new_access}"},
        json={"jsonrpc": "2.0", "id": 13, "method": "ping"},
    )
    assert dead.status_code == 401
