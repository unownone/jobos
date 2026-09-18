"""Phase D: queue claim/ack/nack, 15m leases, role gates, system enqueue."""

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
    if client.app.state.db.admin_bootstrapped() and "hub_session" in client.cookies:
        return
    if client.app.state.db.admin_bootstrapped():
        login = client.post(
            "/api/auth/login",
            json={"email": "owner@example.test", "password": "correct-horse"},
        )
        assert login.status_code == 200, login.text
        return
    token = client.app.state.bootstrap_token
    res = client.post(
        "/api/auth/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "owner@example.test", "password": "correct-horse"},
    )
    assert res.status_code == 200, res.text


def relogin_admin(client: TestClient) -> None:
    client.cookies.clear()
    login = client.post(
        "/api/auth/login",
        json={"email": "owner@example.test", "password": "correct-horse"},
    )
    assert login.status_code == 200, login.text


def mint_track_agents(client: TestClient, track: str, names: list[str]) -> list[str]:
    bootstrap_admin(client)
    created = client.post(
        "/api/invites",
        headers=csrf_headers(client),
        json={"track": track, "max_redemptions": 8, "mode": "owner_then_agents"},
    )
    assert created.status_code == 200, created.text
    invite_id = created.json()["invite"]["id"]
    secret = created.json()["secret"]
    keys: list[str] = []
    for i, name in enumerate(names):
        joined = client.post(
            "/api/auth/join",
            json={
                "invite_id": invite_id,
                "s": secret,
                "display_name": name,
                "metadata": {"model": "test", "harness": "pytest", "bed": f"bed-{i}"},
            },
        )
        assert joined.status_code == 200, joined.text
        keys.append(joined.json()["api_key"])
    return keys


def unlock_discovery_search(client: TestClient) -> None:
    """Ack catalog.refresh so discovery.search claims are not 409 when the pack date is >7 days old."""
    pushed = client.post(
        "/api/queue/push",
        headers=h("maintenance"),
        json={"kind": "catalog.refresh", "payload": {"reason": "pytest"}},
    )
    assert pushed.status_code == 200, pushed.text
    claimed = client.post(
        "/api/queue/claim",
        headers=h("maintenance"),
        json={"kinds": ["catalog.refresh"], "limit": 1},
    )
    assert claimed.status_code == 200, claimed.text
    item_id = claimed.json()["items"][0]["id"]
    acked = client.post(f"/api/queue/ack/{item_id}", headers=h("maintenance"))
    assert acked.status_code == 200, acked.text


def test_meta_lists_queue_kinds(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    res = client.get("/api/meta", headers=h("discovery"))
    assert res.status_code == 200
    body = res.json()
    assert "discovery.search" in body["queue_kinds"]
    assert "apply.ready" in body["queue_kinds"]
    assert body["queue_lease_m"] == 15


def test_two_agents_claim_distinct_items(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    unlock_discovery_search(client)
    keys = mint_track_agents(client, "discovery", ["disc-a", "disc-b"])
    for portal in ("remoteok", "indeed"):
        pushed = client.post(
            "/api/queue/push",
            headers=bearer(keys[0]),
            json={"kind": "discovery.search", "payload": {"portal": portal, "query": "staff"}},
        )
        assert pushed.status_code == 200, pushed.text
        assert pushed.json()["item"]["status"] == "open"
    first = client.post(
        "/api/queue/claim",
        headers=bearer(keys[0]),
        json={"kinds": ["discovery.search"], "limit": 1},
    )
    second = client.post(
        "/api/queue/claim",
        headers=bearer(keys[1]),
        json={"kinds": ["discovery.search"], "limit": 1},
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    a = first.json()["items"][0]
    b = second.json()["items"][0]
    assert a["id"] != b["id"]
    assert a["claimed_by"] != b["claimed_by"]
    third = client.post("/api/queue/claim", headers=bearer(keys[0]), json={"kinds": ["discovery.search"]})
    assert third.json()["count"] == 0


def test_same_item_not_double_claimed_while_lease_valid(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    unlock_discovery_search(client)
    keys = mint_track_agents(client, "discovery", ["one", "two"])
    client.post(
        "/api/queue/push",
        headers=bearer(keys[0]),
        json={"kind": "discovery.search", "payload": {"portal": "wellfound", "query": "ml"}},
    )
    first = client.post("/api/queue/claim", headers=bearer(keys[0]), json={})
    assert first.json()["count"] == 1
    item_id = first.json()["items"][0]["id"]
    second = client.post("/api/queue/claim", headers=bearer(keys[1]), json={})
    assert second.json()["count"] == 0
    mine = client.get("/api/queue/mine", headers=bearer(keys[0]))
    assert mine.json()["count"] == 1
    assert mine.json()["items"][0]["id"] == item_id


def test_expired_lease_stolen_emits_claim_expired(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    unlock_discovery_search(client)
    keys = mint_track_agents(client, "discovery", ["old", "new"])
    client.post(
        "/api/queue/push",
        headers=bearer(keys[0]),
        json={"kind": "discovery.search", "payload": {"portal": "ashby", "query": "eng"}},
    )
    client.app.state.queue.clock.set("2026-09-07T12:00:00Z")
    first = client.post("/api/queue/claim", headers=bearer(keys[0]), json={"kinds": ["discovery.search"]})
    assert first.json()["count"] == 1
    assert first.json()["items"][0]["lease_until"] == "2026-09-07T12:15:00Z"
    client.app.state.queue.clock.set("2026-09-07T12:16:00Z")
    stolen = client.post("/api/queue/claim", headers=bearer(keys[1]), json={"kinds": ["discovery.search"]})
    assert stolen.json()["count"] == 1
    assert stolen.json()["items"][0]["id"] == first.json()["items"][0]["id"]
    events = client.get("/api/events").json()["events"]
    assert "claim_expired" in [e["action"] for e in events]


def test_nack_requeue_then_dead_on_fifth(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    unlock_discovery_search(client)
    keys = mint_track_agents(client, "discovery", ["nack-bot"])
    client.post(
        "/api/queue/push",
        headers=bearer(keys[0]),
        json={"kind": "discovery.search", "payload": {"portal": "greenhouse", "query": "x"}},
    )
    last_status = None
    for i in range(5):
        claimed = client.post("/api/queue/claim", headers=bearer(keys[0]), json={})
        assert claimed.json()["count"] == 1, claimed.text
        item_id = claimed.json()["items"][0]["id"]
        nacked = client.post(
            f"/api/queue/nack/{item_id}",
            headers=bearer(keys[0]),
            json={"requeue": True, "note": f"fail {i+1}"},
        )
        assert nacked.status_code == 200, nacked.text
        last_status = nacked.json()["item"]["status"]
        if i < 4:
            assert last_status == "open"
            assert nacked.json()["item"]["attempts"] == i + 1
    assert last_status == "dead"
    empty = client.post("/api/queue/claim", headers=bearer(keys[0]), json={})
    assert empty.json()["count"] == 0


def test_discovery_cannot_claim_apply_kinds(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    keys = mint_track_agents(client, "discovery", ["disc-only"])
    created = client.post(
        "/api/jobs",
        headers=bearer(keys[0]),
        json={
            "id": "remoteok__queue1",
            "company": "Acme",
            "title": "Staff Engineer",
            "apply_url": "https://jobs.example.com/staff-q",
            "status": "apply_ready",
            "apply_packet": {"url": "https://jobs.example.com/staff-q", "steps": ["Open URL"]},
        },
    )
    assert created.status_code == 201, created.text
    denied = client.post("/api/queue/claim", headers=bearer(keys[0]), json={"kinds": ["apply.ready"]})
    assert denied.status_code == 403
    listed = client.get("/api/queue")
    assert any(row["kind"] == "apply.ready" and row["status"] == "open" for row in listed.json()["items"])


def test_apply_cannot_claim_discovery_search(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    disc = mint_track_agents(client, "discovery", ["d1"])[0]
    apply_key = mint_track_agents(client, "application", ["a1"])[0]
    client.post(
        "/api/queue/push",
        headers=bearer(disc),
        json={"kind": "discovery.search", "payload": {"portal": "lever", "query": "staff"}},
    )
    denied = client.post("/api/queue/claim", headers=bearer(apply_key), json={"kinds": ["discovery.search"]})
    assert denied.status_code == 403
    create_denied = client.post("/api/jobs", headers=bearer(apply_key), json={"company": "Nope", "title": "Nope"})
    assert create_denied.status_code == 403


def test_maintenance_cannot_claim_discovery_search(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    disc = mint_track_agents(client, "discovery", ["d2"])[0]
    maint = mint_track_agents(client, "maintenance", ["m1"])[0]
    client.post(
        "/api/queue/push",
        headers=bearer(disc),
        json={"kind": "discovery.search", "payload": {"portal": "weekday", "query": "backend"}},
    )
    denied = client.post("/api/queue/claim", headers=bearer(maint), json={"kinds": ["discovery.search"]})
    assert denied.status_code == 403


def test_apply_ready_system_enqueue_dedupes(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    disc = mint_track_agents(client, "discovery", ["packet"])[0]
    created = client.post(
        "/api/jobs",
        headers=bearer(disc),
        json={
            "id": "lever__qready",
            "company": "Beta",
            "title": "Engineer",
            "apply_url": "https://jobs.example.com/beta",
            "status": "discovered",
        },
    )
    assert created.status_code == 201
    listed = client.get("/api/queue").json()["items"]
    assert not any(i["kind"] == "apply.ready" for i in listed)
    patched = client.patch(
        "/api/jobs/lever__qready",
        headers=bearer(disc),
        json={"status": "apply_ready", "apply_packet": {"url": "https://jobs.example.com/beta", "steps": ["1"]}},
    )
    assert patched.status_code == 200, patched.text
    again = client.patch("/api/jobs/lever__qready", headers=bearer(disc), json={"notes": "still ready"})
    assert again.status_code == 200
    items = [
        i
        for i in client.get("/api/queue").json()["items"]
        if i["kind"] == "apply.ready" and i["job_id"] == "lever__qready"
    ]
    assert len(items) == 1
    apply_key = mint_track_agents(client, "application", ["applier"])[0]
    claimed = client.post("/api/queue/claim", headers=bearer(apply_key), json={"kinds": ["apply.ready"]})
    assert claimed.json()["count"] == 1
    job = client.get("/api/jobs/lever__qready").json()["job"]
    assert job["owners"]["apply"] == "applier"
    acked = client.post(f"/api/queue/ack/{claimed.json()['items'][0]['id']}", headers=bearer(apply_key))
    assert acked.status_code == 200
    assert acked.json()["item"]["status"] == "acked"


def test_outreach_ready_on_applied(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    disc = mint_track_agents(client, "discovery", ["d-out"])[0]
    apply_key = mint_track_agents(client, "application", ["a-out"])[0]
    created = client.post(
        "/api/jobs",
        headers=bearer(disc),
        json={
            "id": "ashby__out1",
            "company": "Gamma",
            "title": "PM",
            "apply_url": "https://jobs.example.com/gamma",
            "status": "apply_ready",
            "apply_packet": {"url": "https://jobs.example.com/gamma", "steps": ["Apply"]},
        },
    )
    assert created.status_code == 201
    moved = client.patch("/api/jobs/ashby__out1", headers=bearer(apply_key), json={"status": "applied"})
    assert moved.status_code == 200, moved.text
    items = [i for i in client.get("/api/queue").json()["items"] if i["kind"] == "outreach.ready"]
    assert len(items) == 1
    assert items[0]["job_id"] == "ashby__out1"


def test_discovery_cannot_push_apply_ready(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    disc = mint_track_agents(client, "discovery", ["pushy"])[0]
    denied = client.post(
        "/api/queue/push",
        headers=bearer(disc),
        json={"kind": "apply.ready", "job_id": "remoteok__x"},
    )
    assert denied.status_code == 403


def test_three_discovery_bots_no_collision(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    unlock_discovery_search(client)
    keys = mint_track_agents(client, "discovery", ["bot-0", "bot-1", "bot-2"])
    for portal in ("remoteok", "indeed", "wellfound"):
        res = client.post(
            "/api/queue/push",
            headers=bearer(keys[0]),
            json={"kind": "discovery.search", "payload": {"portal": portal, "query": "staff"}},
        )
        assert res.status_code == 200
    job = client.post(
        "/api/jobs",
        headers=bearer(keys[0]),
        json={
            "id": "remoteok__enrich1",
            "company": "Delta",
            "title": "SRE",
            "apply_url": "https://jobs.example.com/delta",
            "status": "discovered",
        },
    )
    assert job.status_code == 201
    ids = []
    for k in keys:
        pushed = client.post(
            "/api/queue/push",
            headers=bearer(k),
            json={"kind": "discovery.enrich", "job_id": "remoteok__enrich1", "payload": {"job_id": "remoteok__enrich1"}},
        )
        assert pushed.status_code == 200
        ids.append(pushed.json()["item"]["id"])
    assert len(set(ids)) == 1

    claimed_ids: list[str] = []
    for key in keys:
        res = client.post(
            "/api/queue/claim",
            headers=bearer(key),
            json={"kinds": ["discovery.search"], "limit": 1},
        )
        assert res.status_code == 200, res.text
        items = res.json().get("items") or []
        assert len(items) == 1
        claimed_ids.append(items[0]["id"])
    assert len(set(claimed_ids)) == 3


def test_compat_apply_still_cannot_create_jobs(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    res = client.post("/api/jobs", headers=h("apply"), json={"company": "Zed", "title": "No"})
    assert res.status_code == 403


def test_discovery_agent_cannot_inspect_full_queue(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    keys = mint_track_agents(client, "discovery", ["owner-d", "nosy"])
    denied = client.get("/api/queue", headers=bearer(keys[1]))
    assert denied.status_code == 403
    owner_ok = client.get("/api/queue", headers=bearer(keys[0]))
    assert owner_ok.status_code == 200
