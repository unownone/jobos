"""Hub memory pods: worker / track / common. Recall every round; store sparingly."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.constants import ROLES
from app.main import create_app
from app.memory_store import skill_draft_from_memory
from app.settings import Settings

TOKENS = {role: f"test-token-{role}-not-real" for role in ROLES}

TRACK_FACT = {
    "pod": "track",
    "kind": "portal_quirk",
    "title": "Greenhouse work-auth radio",
    "body": (
        "Acme Greenhouse asks a work-authorization radio that is missing from the "
        "apply packet. Bounce to discovery instead of guessing the legal answer."
    ),
    "company": "Acme",
}

WORKER_NOTE = {
    "pod": "worker",
    "kind": "working_note",
    "title": "RemoteOK page cursor",
    "body": (
        "Already paged RemoteOK backend staff through page 3. Next loop starts at "
        "page 4 and skips intern posts."
    ),
}

COMMON_FACT = {
    "pod": "common",
    "kind": "tool_failure",
    "title": "Exa MCP hit free rate limit",
    "body": (
        "Exa web_search_exa returned the free MCP rate-limit error. Use Tavily or "
        "Parallel Search until the operator adds an Exa key."
    ),
}


def test_skill_draft_from_memory_maps_discovery_track() -> None:
    draft = skill_draft_from_memory(
        {
            "id": "mem_abc",
            "pod": "track:discovery",
            "kind": "portal_quirk",
            "title": "Greenhouse work-auth radio",
            "body": "Acme Greenhouse asks a work-authorization radio missing from the packet.",
            "company": "Acme",
            "tags": [],
        }
    )
    assert draft["role"] == "discovery"
    assert draft["origin"] == "memory"
    assert draft["origin_ref"] == "mem_abc"
    assert "source" in draft["tags"]
    assert draft["platform"] == "greenhouse"
    assert draft["slug"].startswith("mem-")


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


def test_memory_requires_auth(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    assert client.get("/api/memory/recall").status_code == 401
    assert client.get("/api/memory/items").status_code == 401
    assert client.post("/api/memory/items", json=TRACK_FACT).status_code == 401
    assert client.post("/api/memory/items/mem_missing/solidify", json={}).status_code == 401


def test_heartbeat_includes_memory_card(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    disc = invite_join(client, "discovery", "disc-mem-1")
    beat = client.post("/api/presence/heartbeat", headers=bearer(disc["api_key"]))
    assert beat.status_code == 200, beat.text
    memory = beat.json()["memory"]
    assert memory["recall_url"] == "/api/memory/recall"
    assert memory["write_url"] == "/api/memory/items"
    pods = {row["id"] for row in memory["pods"]}
    assert "common" in pods
    assert any(pid.startswith("track:discovery") for pid in pods)
    assert any(pid.startswith("worker:") for pid in pods)


def test_track_pod_is_shared_and_hidden_from_other_tracks(
    hub: tuple[TestClient, Settings],
) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    disc_a = invite_join(client, "discovery", "disc-a")
    disc_b = invite_join(client, "discovery", "disc-b")
    apply_a = invite_join(client, "application", "apply-a")

    stored = client.post(
        "/api/memory/items",
        headers=bearer(disc_a["api_key"]),
        json=TRACK_FACT,
    )
    assert stored.status_code == 201, stored.text
    item = stored.json()["item"]
    assert item["pod"] == "track:discovery"
    assert item["kind"] == "portal_quirk"

    peer = client.get("/api/memory/recall", headers=bearer(disc_b["api_key"]))
    assert peer.status_code == 200, peer.text
    titles = [row["title"] for row in peer.json()["items"]]
    assert "Greenhouse work-auth radio" in titles

    outsider = client.get(
        "/api/memory/items",
        headers=bearer(apply_a["api_key"]),
        params={"pod": "track:discovery"},
    )
    assert outsider.status_code == 403, outsider.text

    apply_recall = client.get("/api/memory/recall", headers=bearer(apply_a["api_key"]))
    apply_titles = [row["title"] for row in apply_recall.json()["items"]]
    assert "Greenhouse work-auth radio" not in apply_titles


def test_worker_pod_is_private(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    disc_a = invite_join(client, "discovery", "disc-priv-a")
    disc_b = invite_join(client, "discovery", "disc-priv-b")
    created = client.post(
        "/api/memory/items",
        headers=bearer(disc_a["api_key"]),
        json=WORKER_NOTE,
    )
    assert created.status_code == 201, created.text
    assert created.json()["item"]["pod"].startswith("worker:")

    other = client.get("/api/memory/recall", headers=bearer(disc_b["api_key"]))
    titles = [row["title"] for row in other.json()["items"]]
    assert "RemoteOK page cursor" not in titles

    own = client.get("/api/memory/recall", headers=bearer(disc_a["api_key"]))
    own_titles = [row["title"] for row in own.json()["items"]]
    assert "RemoteOK page cursor" in own_titles


def test_common_pod_is_visible_to_every_track(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    maint = invite_join(client, "maintenance", "maint-1")
    disc = invite_join(client, "discovery", "disc-common")
    apply_a = invite_join(client, "application", "apply-common")
    stored = client.post(
        "/api/memory/items",
        headers=bearer(maint["api_key"]),
        json=COMMON_FACT,
    )
    assert stored.status_code == 201, stored.text
    assert stored.json()["item"]["pod"] == "common"
    for key in (disc["api_key"], apply_a["api_key"]):
        recall = client.get("/api/memory/recall", headers=bearer(key))
        titles = [row["title"] for row in recall.json()["items"]]
        assert "Exa MCP hit free rate limit" in titles


def test_write_gates_reject_aggressive_and_secret_payloads(
    hub: tuple[TestClient, Settings],
) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    disc = invite_join(client, "discovery", "disc-gates")
    headers = bearer(disc["api_key"])
    short = client.post(
        "/api/memory/items",
        headers=headers,
        json={"pod": "track", "kind": "portal_quirk", "title": "Too short", "body": "Nope."},
    )
    assert short.status_code == 422, short.text
    secret = client.post(
        "/api/memory/items",
        headers=headers,
        json={
            "pod": "common",
            "kind": "hub_note",
            "title": "Saved a hub key",
            "body": "Do not keep jh_agt_this-is-not-real in the common memory pod ever.",
        },
    )
    assert secret.status_code == 422, secret.text
    dump = client.post(
        "/api/memory/items",
        headers=headers,
        json={
            "pod": "track",
            "kind": "company_note",
            "title": "Full JD paste",
            "body": '{"description": "long job description follows with transcript text"} extra',
        },
    )
    assert dump.status_code == 422, dump.text
    wrong_kind = client.post(
        "/api/memory/items",
        headers=headers,
        json={**TRACK_FACT, "pod": "common", "kind": "portal_quirk"},
    )
    assert wrong_kind.status_code == 422, wrong_kind.text


def test_dedup_and_track_write_budget(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    disc = invite_join(client, "discovery", "disc-budget")
    headers = bearer(disc["api_key"])
    first = client.post("/api/memory/items", headers=headers, json=TRACK_FACT)
    assert first.status_code == 201, first.text
    again = client.post("/api/memory/items", headers=headers, json=TRACK_FACT)
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "exists"

    for idx in range(2):
        body = {
            "pod": "track",
            "kind": "search_coverage",
            "title": f"RemoteOK sweep batch {idx + 1} done",
            "body": (
                f"Finished RemoteOK staff-backend sweep batch {idx + 1} through the public "
                "JSON feed. Next discovery worker should start after this cursor."
            ),
        }
        res = client.post("/api/memory/items", headers=headers, json=body)
        assert res.status_code == 201, res.text

    blocked = client.post(
        "/api/memory/items",
        headers=headers,
        json={
            "pod": "track",
            "kind": "blocker",
            "title": "Hiring Cafe parser flake",
            "body": (
                "Hiring Cafe public pages returned empty __NEXT_DATA__ twice this round. "
                "Skip the portal until the next cycle instead of retrying immediately."
            ),
        },
    )
    assert blocked.status_code == 429, blocked.text
    assert blocked.json()["detail"]["code"] == "memory_rate_limited"


def test_compat_actor_gets_private_worker_pod(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    created = client.post("/api/memory/items", headers=h("discovery", "alpha"), json=WORKER_NOTE)
    assert created.status_code == 201, created.text
    mine = client.get("/api/memory/recall", headers=h("discovery", "alpha"))
    assert "RemoteOK page cursor" in [row["title"] for row in mine.json()["items"]]
    other = client.get("/api/memory/recall", headers=h("discovery", "beta"))
    assert "RemoteOK page cursor" not in [row["title"] for row in other.json()["items"]]


def test_onboarding_and_meta_advertise_memory(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    disc = invite_join(client, "discovery", "disc-onboard")
    onboard = client.get("/api/onboarding", headers=bearer(disc["api_key"]))
    assert onboard.status_code == 200, onboard.text
    memory = onboard.json()["memory"]
    assert memory["recall"] == "/api/memory/recall"
    assert memory["use_every_round"] is True
    paths = [row["path"] for row in onboard.json()["readings"]]
    assert "docs/job-hub/memory.md" in paths
    meta = client.get("/api/meta", headers=bearer(disc["api_key"]))
    assert meta.json()["memory"]["pods"] == ["worker", "track", "common"]


def test_queue_claim_includes_memory(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    disc = invite_join(client, "discovery", "disc-claim")
    claimed = client.post(
        "/api/queue/claim",
        headers=bearer(disc["api_key"]),
        json={"limit": 1},
    )
    assert claimed.status_code == 200, claimed.text
    assert "memory" in claimed.json()
    assert claimed.json()["memory"]["recall_url"] == "/api/memory/recall"


def test_solidify_track_fact_becomes_memory_origin_skill(
    hub: tuple[TestClient, Settings],
) -> None:
    client, _settings = hub
    bootstrap_admin(client)
    disc_a = invite_join(client, "discovery", "disc-solid-a")
    disc_b = invite_join(client, "discovery", "disc-solid-b")
    maint = invite_join(client, "maintenance", "maint-solid", mode="owner_then_agents")

    stored = client.post(
        "/api/memory/items",
        headers=bearer(disc_a["api_key"]),
        json=TRACK_FACT,
    )
    assert stored.status_code == 201, stored.text
    item_id = stored.json()["item"]["id"]

    stolen = client.post(
        f"/api/memory/items/{item_id}/solidify",
        headers=bearer(disc_b["api_key"]),
        json={},
    )
    assert stolen.status_code == 403, stolen.text

    solid = client.post(
        f"/api/memory/items/{item_id}/solidify",
        headers=bearer(disc_a["api_key"]),
        json={},
    )
    assert solid.status_code == 200, solid.text
    assert solid.json()["status"] == "queued"
    recording = solid.json()["recording"]
    payload = recording["payload"]
    assert payload["origin"] == "memory"
    assert payload["origin_ref"] == item_id
    assert payload["role"] == "discovery"
    assert "source" in payload["tags"]
    assert payload["platform"] == "greenhouse"
    assert solid.json()["item"]["solidify_status"] == "queued"
    recording_id = recording["id"]
    queue_id = solid.json()["queue_item"]["id"]

    again = client.post(
        f"/api/memory/items/{item_id}/solidify",
        headers=bearer(disc_a["api_key"]),
        json={},
    )
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "exists"
    assert again.json()["recording"]["id"] == recording_id

    denied = client.post(
        "/api/queue/claim",
        headers=bearer(disc_a["api_key"]),
        json={"kinds": ["skill.record"]},
    )
    assert denied.status_code == 403

    claimed = client.post(
        "/api/queue/claim",
        headers=bearer(maint["api_key"]),
        json={"kinds": ["skill.record"]},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["items"][0]["id"] == queue_id

    proctor = client.post(
        f"/api/registry/recordings/{recording_id}/proctor",
        headers=bearer(maint["api_key"]),
        json={"verdict": "pass", "note": "reusable greenhouse quirk"},
    )
    assert proctor.status_code == 200, proctor.text

    promoted = client.post(
        f"/api/registry/recordings/{recording_id}/promote",
        headers=bearer(maint["api_key"]),
    )
    assert promoted.status_code == 200, promoted.text
    skill = promoted.json()["skill"]
    assert skill["scope"] == "shared"
    assert skill["status"] == "approved"
    assert skill["origin"] == "memory"
    assert skill["origin_ref"] == item_id
    assert skill["slug"].startswith("mem-")

    visible = client.get("/api/registry/skills", headers=bearer(disc_b["api_key"]))
    slugs = {row["slug"] for row in visible.json()["skills"]}
    assert skill["slug"] in slugs

    recalled = client.get("/api/memory/items", headers=bearer(disc_a["api_key"]))
    fact = next(row for row in recalled.json()["items"] if row["id"] == item_id)
    assert fact["solidify_status"] == "promoted"
    assert fact["recording_id"] == recording_id


def test_worker_notes_cannot_solidify(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    created = client.post("/api/memory/items", headers=h("discovery"), json=WORKER_NOTE)
    assert created.status_code == 201, created.text
    item_id = created.json()["item"]["id"]
    blocked = client.post(
        f"/api/memory/items/{item_id}/solidify",
        headers=h("discovery"),
        json={},
    )
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["detail"]["code"] == "memory_forbidden"


def test_common_fact_solidify_maps_to_maintain(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    created = client.post("/api/memory/items", headers=h("discovery"), json=COMMON_FACT)
    assert created.status_code == 201, created.text
    item_id = created.json()["item"]["id"]
    solid = client.post(
        f"/api/memory/items/{item_id}/solidify",
        headers=h("discovery"),
        json={},
    )
    assert solid.status_code == 200, solid.text
    payload = solid.json()["recording"]["payload"]
    assert payload["role"] == "maintain"
    assert "maintain" in payload["tags"]
    assert payload["origin"] == "memory"
