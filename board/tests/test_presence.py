"""Phase C: heartbeat, presence statuses, admin directory. No API keys in payloads."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import require_principal
from app.constants import ROLES
from app.main import create_app
from app.presence import IDLE_AFTER_S, STALE_AFTER_S, derive_status, mount_presence
from app.settings import Settings

TOKENS = {role: f"test-token-{role}-not-real" for role in ROLES}


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


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
def hub(tmp_path: Path) -> tuple[TestClient, Settings, Clock]:
    settings = _settings(tmp_path)
    app = create_app(settings)
    mount_presence(app, app.state.db, require_principal(settings, app.state.db))
    clock = Clock()
    app.state.clock = clock
    return TestClient(app), settings, clock


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


def invite_join(
    client: TestClient,
    *,
    track: str,
    display_name: str,
    metadata: dict | None = None,
) -> dict:
    created = client.post(
        "/api/invites",
        headers=csrf_headers(client),
        json={"track": track, "max_redemptions": 8, "ttl_hours": 72, "mode": "owner_then_agents"},
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    joined = client.post(
        "/api/auth/join",
        json={
            "invite_id": payload["invite"]["id"],
            "s": payload["secret"],
            "display_name": display_name,
            "metadata": metadata
            or {
                "model": "grok-4",
                "harness": "cursor-cloud",
                "bed": "cursor",
            },
        },
    )
    assert joined.status_code == 200, joined.text
    return joined.json()


def test_heartbeat_unauthenticated_401(hub: tuple[TestClient, Settings, Clock]) -> None:
    client, _settings, _clock = hub
    res = client.post("/api/presence/heartbeat", json={"status_hint": "logged_in"})
    assert res.status_code == 401


def test_heartbeat_logged_in_then_stale(hub: tuple[TestClient, Settings, Clock]) -> None:
    client, _settings, clock = hub
    bootstrap_admin(client)
    ping = client.post(
        "/api/presence/heartbeat",
        headers=csrf_headers(client),
        json={"status_hint": "logged_in"},
    )
    assert ping.status_code == 200, ping.text
    body = ping.json()
    assert body["status"] == "logged_in"
    assert body["heartbeat_s"] == 10
    assert body["stale_after_s"] == 30
    assert body["pending_messages"] == []
    assert "api_key" not in str(body).lower()
    listed = client.get("/api/presence")
    assert listed.status_code == 200
    users = listed.json()["users"]
    assert any(u["status"] == "logged_in" for u in users)
    clock.advance(STALE_AFTER_S + 1)
    stale = client.get("/api/presence")
    assert stale.status_code == 200
    statuses = {u["user_id"]: u["status"] for u in stale.json()["users"]}
    admin_id = client.get("/api/auth/me").json()["user_id"]
    assert statuses[admin_id] == "stale"


def test_idle_after_sixty_seconds_of_heartbeats(
    hub: tuple[TestClient, Settings, Clock],
) -> None:
    client, _settings, clock = hub
    bootstrap_admin(client)
    client.post("/api/presence/heartbeat", headers=csrf_headers(client), json={"status_hint": "logged_in"})
    for _ in range(7):
        clock.advance(10)
        again = client.post(
            "/api/presence/heartbeat",
            headers=csrf_headers(client),
            json={"status_hint": "logged_in"},
        )
        assert again.status_code == 200, again.text
    assert again.json()["status"] == "idle"


def test_working_and_producing_hints(hub: tuple[TestClient, Settings, Clock]) -> None:
    client, _settings, _clock = hub
    bootstrap_admin(client)
    owner = invite_join(client, track="discovery", display_name="disc-owner")
    key = owner["api_key"]
    headers = {"Authorization": f"Bearer {key}"}
    working = client.post(
        "/api/presence/heartbeat",
        headers=headers,
        json={"status_hint": "working", "task_id": "board__acme-swe", "task_kind": "job", "job_id": "board__acme-swe"},
    )
    assert working.status_code == 200, working.text
    assert working.json()["status"] == "working"
    assert working.json()["self"]["current_task"]["id"] == "board__acme-swe"
    producing = client.post(
        "/api/presence/heartbeat",
        headers=headers,
        json={"status_hint": "working", "producing": True, "task_id": "board__acme-swe"},
    )
    assert producing.json()["status"] == "producing"
    hint_producing = client.post(
        "/api/presence/heartbeat",
        headers=headers,
        json={"status_hint": "producing", "task_id": "opaque-1"},
    )
    assert hint_producing.json()["status"] == "producing"
    logged = client.post(
        "/api/presence/heartbeat",
        headers=headers,
        json={"status_hint": "logged_in", "producing": True},
    )
    assert logged.json()["status"] == "logged_in"


def test_keys_never_in_presence_payload(hub: tuple[TestClient, Settings, Clock]) -> None:
    client, _settings, _clock = hub
    bootstrap_admin(client)
    owner = invite_join(
        client,
        track="application",
        display_name="apply-owner",
        metadata={
            "model": "claude",
            "harness": "cursor",
            "bed": "local",
            "api_key": "jh_agt_should_not_leak_xxxxx",
            "token": "role-token-secret",
        },
    )
    key = owner["api_key"]
    assert key.startswith("jh_")
    client.post(
        "/api/presence/heartbeat",
        headers={"Authorization": f"Bearer {key}"},
        json={"status_hint": "logged_in"},
    )
    listed = client.get("/api/presence")
    blob = listed.text
    assert key not in blob
    assert "jh_agt_should_not_leak" not in blob
    assert "role-token-secret" not in blob
    assert "password_hash" not in blob
    assert "key_hash" not in blob
    row = next(u for u in listed.json()["users"] if u["display_name"] == "apply-owner")
    assert row["model"] == "claude"
    assert row["harness"] == "cursor"
    assert row["bed"] == "local"
    assert row["kind"] == "owner"
    assert row["track"] == "application"
    assert "api_key" not in row


def test_owner_sees_own_track_only(hub: tuple[TestClient, Settings, Clock]) -> None:
    client, _settings, _clock = hub
    bootstrap_admin(client)
    disc = invite_join(client, track="discovery", display_name="d-owner")
    out = invite_join(client, track="outreach", display_name="o-owner")
    client.post(
        "/api/presence/heartbeat",
        headers={"Authorization": f"Bearer {disc['api_key']}"},
        json={"status_hint": "logged_in"},
    )
    client.post(
        "/api/presence/heartbeat",
        headers={"Authorization": f"Bearer {out['api_key']}"},
        json={"status_hint": "working"},
    )
    as_disc = client.get("/api/presence", headers={"Authorization": f"Bearer {disc['api_key']}"})
    assert as_disc.status_code == 200
    names = {u["display_name"] for u in as_disc.json()["users"]}
    assert "d-owner" in names
    assert "o-owner" not in names
    agent = client.post(
        "/api/agents",
        headers={"Authorization": f"Bearer {disc['api_key']}"},
        json={"display_name": "d-agent", "metadata": {"model": "gpt"}},
    )
    assert agent.status_code == 200
    agent_key = agent.json()["api_key"]
    client.post(
        "/api/presence/heartbeat",
        headers={"Authorization": f"Bearer {agent_key}"},
        json={"status_hint": "idle"},
    )
    forbidden = client.get("/api/presence", headers={"Authorization": f"Bearer {agent_key}"})
    assert forbidden.status_code == 403


def test_admin_users_directory_and_page(hub: tuple[TestClient, Settings, Clock]) -> None:
    client, _settings, _clock = hub
    bootstrap_admin(client)
    invite_join(client, track="maintenance", display_name="hygiene-owner")
    listed = client.get("/api/users")
    assert listed.status_code == 200
    blob = listed.text
    assert "jh_own_" not in blob
    assert "jh_agt_" not in blob
    ids = {u["display_name"] for u in listed.json()["users"]}
    assert "hygiene-owner" in ids
    page = client.get("/admin/users")
    assert page.status_code == 200
    assert "Directory" in page.text
    as_owner = client.post(
        "/api/auth/join",
        json={
            "invite_id": "nope",
            "s": "nope",
            "display_name": "x",
        },
    )
    assert as_owner.status_code in {401, 404}


def test_compat_connect_can_heartbeat(hub: tuple[TestClient, Settings, Clock]) -> None:
    client, _settings, _clock = hub
    res = client.post(
        "/api/presence/heartbeat",
        headers={"X-Role": "admin", "X-Token": TOKENS["admin"], "X-Actor": "compat-admin"},
        json={"status_hint": "logged_in"},
    )
    assert res.status_code == 200, res.text
    listed = client.get(
        "/api/presence",
        headers={"X-Role": "admin", "X-Token": TOKENS["admin"]},
    )
    assert listed.status_code == 200
    kinds = {u["kind"] for u in listed.json()["users"]}
    assert "compat" in kinds


def test_derive_status_unit() -> None:
    now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
    hb = now - timedelta(seconds=5)
    assert (
        derive_status(
            last_heartbeat=hb,
            connected_at=now - timedelta(seconds=10),
            status_hint="logged_in",
            producing_flag=False,
            has_claim=False,
            recent_write=False,
            now=now,
        )
        == "logged_in"
    )
    assert (
        derive_status(
            last_heartbeat=now - timedelta(seconds=31),
            connected_at=now - timedelta(seconds=40),
            status_hint="working",
            producing_flag=True,
            has_claim=True,
            recent_write=True,
            now=now,
        )
        == "stale"
    )
    assert (
        derive_status(
            last_heartbeat=hb,
            connected_at=now - timedelta(seconds=70),
            status_hint=None,
            producing_flag=False,
            has_claim=False,
            recent_write=False,
            now=now,
        )
        == "idle"
    )
    assert (
        derive_status(
            last_heartbeat=hb,
            connected_at=hb,
            status_hint="working",
            producing_flag=False,
            has_claim=False,
            recent_write=True,
            now=now,
        )
        == "producing"
    )
