"""Phase G: inter-agent Hub inbox (not employer email/SMS/InMail)."""

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


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


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


def invite_join(client: TestClient, track: str, display_name: str, *, mode: str = "agents_only") -> dict:
    created = client.post(
        "/api/invites",
        headers=csrf_headers(client),
        json={"track": track, "max_redemptions": 8, "mode": mode},
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


def test_messages_require_auth(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    assert client.get("/api/messages").status_code == 401
    assert client.post("/api/messages", json={"type": "note", "body": "hi", "to_track": "application"}).status_code == 401
    assert client.post("/api/presence/heartbeat").status_code == 401


def test_discovery_broadcast_to_application_track(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    discovery = invite_join(client, "discovery", "disc-1")
    apply_a = invite_join(client, "application", "apply-1")
    apply_b = invite_join(client, "application", "apply-2")
    outreach = invite_join(client, "outreach", "out-1")

    sent = client.post(
        "/api/messages",
        headers=bearer(discovery["api_key"]),
        json={
            "type": "handoff",
            "body": "packet ready for Acme staff role",
            "to_track": "apply",
            "job_id": "remoteok__acme-staff",
        },
    )
    assert sent.status_code == 201, sent.text
    msg = sent.json()["message"]
    assert msg["type"] == "handoff"
    assert msg["to_track"] == "application"
    assert msg["job_id"] == "remoteok__acme-staff"
    assert msg["to_user_id"] is None

    inbox_apply = client.get(
        "/api/messages",
        headers=bearer(apply_a["api_key"]),
        params={"unread": "1"},
    )
    assert inbox_apply.status_code == 200, inbox_apply.text
    body = inbox_apply.json()
    assert body["pending_messages"] == 1
    assert body["count"] == 1
    assert body["messages"][0]["id"] == msg["id"]
    assert body["messages"][0]["read"] is False

    inbox_apply_b = client.get("/api/messages", headers=bearer(apply_b["api_key"]))
    assert inbox_apply_b.json()["pending_messages"] == 1

    inbox_out = client.get("/api/messages", headers=bearer(outreach["api_key"]))
    assert inbox_out.json()["messages"] == []
    assert inbox_out.json()["pending_messages"] == 0

    inbox_disc = client.get("/api/messages", headers=bearer(discovery["api_key"]))
    assert inbox_disc.json()["messages"] == []

    sent_box = client.get(
        "/api/messages",
        headers=bearer(discovery["api_key"]),
        params={"sent": "1"},
    )
    assert sent_box.json()["count"] == 1


def test_cannot_send_to_email_or_employer_channels(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    agent = invite_join(client, "discovery", "disc-mail")
    headers = bearer(agent["api_key"])

    email_to = client.post(
        "/api/messages",
        headers=headers,
        json={
            "type": "note",
            "body": "please apply",
            "to": "recruiter@acme.example",
        },
    )
    assert email_to.status_code == 422, email_to.text

    to_email = client.post(
        "/api/messages",
        headers=headers,
        json={
            "type": "note",
            "body": "please apply",
            "to_track": "application",
            "to_email": "recruiter@acme.example",
        },
    )
    assert to_email.status_code == 422

    sms = client.post(
        "/api/messages",
        headers=headers,
        json={"type": "sms", "body": "hi", "to_track": "application"},
    )
    assert sms.status_code == 422

    inmail = client.post(
        "/api/messages",
        headers=headers,
        json={
            "type": "note",
            "body": "hi",
            "to_track": "application",
            "channel": "inmail",
        },
    )
    assert inmail.status_code == 422

    whatsapp = client.post(
        "/api/messages",
        headers=headers,
        json={"kind": "whatsapp", "body": "hi", "to_track": "application"},
    )
    assert whatsapp.status_code == 422


def test_direct_user_isolation_and_admin_reads_all(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    disc = invite_join(client, "discovery", "disc-dm")
    apply_user = invite_join(client, "application", "apply-dm")
    other = invite_join(client, "application", "apply-other")

    dm = client.post(
        "/api/messages",
        headers=bearer(disc["api_key"]),
        json={
            "type": "question",
            "body": "is the Greenhouse login in the pack?",
            "to_user_id": apply_user["user"]["id"],
            "job_id": "gh__123",
        },
    )
    assert dm.status_code == 201, dm.text
    msg_id = dm.json()["message"]["id"]

    seen = client.get("/api/messages", headers=bearer(apply_user["api_key"]))
    assert seen.json()["count"] == 1
    hidden = client.get("/api/messages", headers=bearer(other["api_key"]))
    assert hidden.json()["count"] == 0

    admin_inbox = client.get("/api/messages")
    assert admin_inbox.status_code == 200
    assert any(m["id"] == msg_id for m in admin_inbox.json()["messages"])


def test_read_receipts_and_heartbeat_pending(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    disc = invite_join(client, "discovery", "disc-read")
    apply_user = invite_join(client, "application", "apply-read")
    apply_peer = invite_join(client, "application", "apply-peer")

    client.post(
        "/api/messages",
        headers=bearer(disc["api_key"]),
        json={"type": "block", "body": "captcha on the ATS", "to_track": "application"},
    )

    beat = client.post("/api/presence/heartbeat", headers=bearer(apply_user["api_key"]))
    assert beat.status_code == 200, beat.text
    assert beat.json()["pending_messages"] == 1
    assert beat.json()["ok"] is True

    inbox = client.get(
        "/api/messages",
        headers=bearer(apply_user["api_key"]),
        params={"unread": "true"},
    )
    msg_id = inbox.json()["messages"][0]["id"]
    receipt = client.post(
        f"/api/messages/{msg_id}/read",
        headers=bearer(apply_user["api_key"]),
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["message"]["read"] is True
    assert receipt.json()["message"]["read_at"]
    assert receipt.json()["pending_messages"] == 0

    after = client.get(
        "/api/messages",
        headers=bearer(apply_user["api_key"]),
        params={"unread": "1"},
    )
    assert after.json()["pending_messages"] == 0
    assert after.json()["count"] == 0

    peer = client.post("/api/presence/heartbeat", headers=bearer(apply_peer["api_key"]))
    assert peer.json()["pending_messages"] == 1

    steal = client.post(
        f"/api/messages/{msg_id}/read",
        headers=bearer(disc["api_key"]),
    )
    assert steal.status_code == 403

    missing = client.post(
        "/api/messages/msg_does_not_exist/read",
        headers=bearer(apply_user["api_key"]),
    )
    assert missing.status_code == 404


def test_message_admin_and_session_cookie(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    apply_user = invite_join(client, "application", "apply-admin-msg")
    posted = client.post(
        "/api/messages",
        headers=csrf_headers(client),
        json={"type": "note", "body": "human is here", "to": "admin"},
    )
    assert posted.status_code == 201, posted.text
    assert posted.json()["message"]["to_track"] == "admin"

    from_apply = client.post(
        "/api/messages",
        headers=bearer(apply_user["api_key"]),
        json={"type": "block", "body": "need work-auth answer", "to": "admin"},
    )
    assert from_apply.status_code == 201, from_apply.text

    admin_list = client.get("/api/messages", params={"unread": "1"})
    types = {m["type"] for m in admin_list.json()["messages"]}
    assert "note" in types
    assert "block" in types

    apply_inbox = client.get("/api/messages", headers=bearer(apply_user["api_key"]))
    assert apply_inbox.json()["messages"] == []
    assert apply_inbox.json()["pending_messages"] == 0


def test_compat_role_can_push_and_pull_track(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    posted = client.post(
        "/api/messages",
        headers=h("discovery"),
        json={"type": "note", "body": "compat ping", "to_track": "application"},
    )
    assert posted.status_code == 201, posted.text
    seen = client.get("/api/messages", headers=h("apply"))
    assert seen.json()["pending_messages"] == 1
    hidden = client.get("/api/messages", headers=h("outreach"))
    assert hidden.json()["pending_messages"] == 0
    admin = client.get("/api/messages", headers=h("admin"))
    assert admin.json()["count"] >= 1
