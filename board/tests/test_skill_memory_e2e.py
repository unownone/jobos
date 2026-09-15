"""E2E: live skill registry + memory pods through a multi-agent Hub round.

In-process FastAPI TestClient (CI ``pytest -m e2e``). Covers the loop agents
must run: onboarding → heartbeat/recall → pick a tagged skill → store a durable
fact → solidify → maintainer-only claim/proctor/promote → other bots use the
shared playbook. GitHub seed must not clobber a promoted memory skill.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.constants import ROLES
from app.main import create_app
from app.settings import Settings

TOKENS = {role: f"test-token-{role}-not-real" for role in ROLES}

WORKDAY_A = "https://acme.myworkdayjobs.com/en-US/job/1"
WORKDAY_B = "https://globex.myworkdayjobs.com/en-US/job/99"
GREENHOUSE_URL = "https://boards.greenhouse.io/acme/jobs/1"

WORKDAY_QUIRK = {
    "pod": "track",
    "kind": "portal_quirk",
    "title": "Workday req id before submit",
    "body": (
        "Every Workday tenant shows a requisition id field that must match the "
        "packet before submit. Same steps for any *.myworkdayjobs.com job. "
        "Do not invent a different tenant URL."
    ),
    "company": "Acme",
}


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
def hub(tmp_path: Path) -> TestClient:
    return TestClient(create_app(_settings(tmp_path)))


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


def invite_join(
    client: TestClient,
    track: str,
    display_name: str,
    *,
    mode: str = "agents_only",
) -> dict:
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


def slugs(res) -> set[str]:
    assert res.status_code == 200, res.text
    return {row["slug"] for row in res.json()["skills"]}


def test_e2e_agent_round_onboarding_heartbeat_registry_memory_solidify_promote(
    hub: TestClient,
) -> None:
    client = hub
    bootstrap_admin(client)
    disc_a = invite_join(client, "discovery", "e2e-disc-a")
    disc_b = invite_join(client, "discovery", "e2e-disc-b")
    apply_a = invite_join(client, "application", "e2e-apply-a")
    apply_b = invite_join(client, "application", "e2e-apply-b")
    maint = invite_join(client, "maintenance", "e2e-maint", mode="owner_then_agents")

    disc_key = bearer(disc_a["api_key"])
    apply_key = bearer(apply_a["api_key"])
    maint_key = bearer(maint["api_key"])

    onboard = client.get("/api/onboarding", headers=disc_key)
    assert onboard.status_code == 200, onboard.text
    body = onboard.json()
    assert body["registry"] == "/api/registry/skills"
    assert body["memory"]["recall"] == "/api/memory/recall"
    assert body["memory"]["write"] == "/api/memory/items"
    assert body["memory"]["solidify"] == "/api/memory/items/{id}/solidify"
    assert body["memory"]["use_every_round"] is True
    readings = {row["path"] for row in body["readings"]}
    assert "docs/job-hub/memory.md" in readings
    assert "docs/catalogs/skill-outline.md" in readings

    beat = client.post("/api/presence/heartbeat", headers=disc_key)
    assert beat.status_code == 200, beat.text
    memory = beat.json()["memory"]
    assert memory["recall_url"] == "/api/memory/recall"
    assert memory["write_url"] == "/api/memory/items"
    assert memory["solidify_url"] == "/api/memory/items/{id}/solidify"

    recall = client.get("/api/memory/recall", headers=disc_key)
    assert recall.status_code == 200, recall.text

    sources = client.get("/api/registry/skills", headers=disc_key, params={"tag": "source"})
    assert {"job-discovery", "source-indeed"} <= slugs(sources)
    apply_playbooks = client.get(
        "/api/registry/skills",
        headers=apply_key,
        params={"tag": "apply", "ats": "workday", "url": WORKDAY_A},
    )
    assert "apply-workday" in slugs(apply_playbooks)
    also_b = client.get(
        "/api/registry/skills",
        headers=apply_key,
        params={"tag": "apply", "url": WORKDAY_B},
    )
    assert "apply-workday" in slugs(also_b)
    not_gh = client.get(
        "/api/registry/skills",
        headers=apply_key,
        params={"tag": "apply", "url": GREENHOUSE_URL},
    )
    assert "apply-workday" not in slugs(not_gh)

    stored = client.post("/api/memory/items", headers=apply_key, json=WORKDAY_QUIRK)
    assert stored.status_code == 201, stored.text
    item = stored.json()["item"]
    assert item["pod"] == "track:application"
    item_id = item["id"]

    peer_apply = client.get("/api/memory/recall", headers=bearer(apply_b["api_key"]))
    assert "Workday req id before submit" in [row["title"] for row in peer_apply.json()["items"]]
    disc_recall = client.get("/api/memory/recall", headers=disc_key)
    assert "Workday req id before submit" not in [row["title"] for row in disc_recall.json()["items"]]

    stolen = client.post(
        f"/api/memory/items/{item_id}/solidify",
        headers=bearer(apply_b["api_key"]),
        json={},
    )
    assert stolen.status_code == 403, stolen.text

    solid = client.post(
        f"/api/memory/items/{item_id}/solidify",
        headers=apply_key,
        json={},
    )
    assert solid.status_code == 200, solid.text
    assert solid.json()["status"] == "queued"
    recording = solid.json()["recording"]
    payload = recording["payload"]
    assert payload["origin"] == "memory"
    assert payload["role"] == "apply"
    assert "apply" in payload["tags"]
    assert payload["platform"] == "workday"
    assert "*.myworkdayjobs.com/*" in payload["match"]["url_patterns"]
    recording_id = recording["id"]
    queue_id = solid.json()["queue_item"]["id"]

    denied_apply = client.post(
        "/api/queue/claim",
        headers=apply_key,
        json={"kinds": ["skill.record"]},
    )
    assert denied_apply.status_code == 403
    denied_disc = client.post(
        "/api/queue/claim",
        headers=disc_key,
        json={"kinds": ["skill.record"]},
    )
    assert denied_disc.status_code == 403

    claimed = client.post(
        "/api/queue/claim",
        headers=maint_key,
        json={"kinds": ["skill.record"]},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["items"][0]["id"] == queue_id
    assert claimed.json()["memory"]["recall_url"] == "/api/memory/recall"

    too_soon = client.post(
        f"/api/registry/recordings/{recording_id}/promote",
        headers=maint_key,
    )
    assert too_soon.status_code == 409

    proctor = client.post(
        f"/api/registry/recordings/{recording_id}/proctor",
        headers=maint_key,
        json={"verdict": "pass", "note": "reproducible across Workday tenants"},
    )
    assert proctor.status_code == 200, proctor.text
    promoted = client.post(
        f"/api/registry/recordings/{recording_id}/promote",
        headers=maint_key,
    )
    assert promoted.status_code == 200, promoted.text
    skill = promoted.json()["skill"]
    assert skill["scope"] == "shared"
    assert skill["status"] == "approved"
    assert skill["origin"] == "memory"
    assert skill["slug"].startswith("mem-")

    other = client.get("/api/registry/skills", headers=bearer(apply_b["api_key"]))
    by_slug = {row["slug"]: row for row in other.json()["skills"]}
    assert by_slug[skill["slug"]]["origin"] == "memory"
    shared = client.get(
        f"/api/registry/skills/{skill['id']}",
        headers=bearer(disc_b["api_key"]),
    )
    assert shared.status_code == 200, shared.text
    assert shared.json()["skill"]["origin"] == "memory"

    job_a = client.get(
        "/api/registry/skills",
        headers=bearer(apply_b["api_key"]),
        params={"url": WORKDAY_A, "tag": "apply"},
    )
    job_b = client.get(
        "/api/registry/skills",
        headers=bearer(apply_b["api_key"]),
        params={"url": WORKDAY_B, "tag": "apply"},
    )
    assert skill["slug"] in slugs(job_a)
    assert skill["slug"] in slugs(job_b)

    recalled = client.get("/api/memory/items", headers=apply_key)
    fact = next(row for row in recalled.json()["items"] if row["id"] == item_id)
    assert fact["solidify_status"] == "promoted"


def test_e2e_github_seed_and_pack_rebuild_skip_promoted_memory_workday(
    hub: TestClient,
) -> None:
    client = hub
    bootstrap_admin(client)
    apply_a = invite_join(client, "application", "e2e-apply-seed")
    maint = invite_join(client, "maintenance", "e2e-maint-seed", mode="owner_then_agents")
    apply_key = bearer(apply_a["api_key"])
    maint_key = bearer(maint["api_key"])

    before = client.get("/api/registry/skills", headers=apply_key)
    listed = [row for row in before.json()["skills"] if row["slug"] == "apply-workday"]
    assert listed and listed[0]["origin"] == "github"

    stored = client.post("/api/memory/items", headers=apply_key, json=WORKDAY_QUIRK)
    assert stored.status_code == 201, stored.text
    item_id = stored.json()["item"]["id"]
    solid = client.post(
        f"/api/memory/items/{item_id}/solidify",
        headers=apply_key,
        json={
            "slug": "apply-workday",
            "name": "Workday apply",
            "tags": ["apply", "ats", "workday"],
            "platform": "workday",
            "match": {
                "ats": ["workday"],
                "url_patterns": ["*.myworkdayjobs.com/*", "*workday.com/*"],
                "apply_kind": ["ats"],
            },
        },
    )
    assert solid.status_code == 200, solid.text
    recording_id = solid.json()["recording"]["id"]

    claimed = client.post(
        "/api/queue/claim",
        headers=maint_key,
        json={"kinds": ["skill.record"]},
    )
    assert claimed.status_code == 200, claimed.text
    proctor = client.post(
        f"/api/registry/recordings/{recording_id}/proctor",
        headers=maint_key,
        json={"verdict": "pass", "note": "general Workday req-id check"},
    )
    assert proctor.status_code == 200, proctor.text
    promoted = client.post(
        f"/api/registry/recordings/{recording_id}/promote",
        headers=maint_key,
    )
    assert promoted.status_code == 200, promoted.text
    skill = promoted.json()["skill"]
    assert skill["slug"] == "apply-workday"
    assert skill["origin"] == "memory"
    assert skill["origin_ref"] == item_id

    seeded = client.post("/api/registry/seed", headers=maint_key)
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["counts"]["skipped"] >= 1

    rebuilt = client.post("/api/packs/rebuild", headers=maint_key)
    assert rebuilt.status_code == 200, rebuilt.text

    after = client.get(
        "/api/registry/skills",
        headers=apply_key,
        params={"url": WORKDAY_B, "tag": "apply"},
    )
    workday = next(row for row in after.json()["skills"] if row["slug"] == "apply-workday")
    assert workday["origin"] == "memory"
    assert "req" in workday["body"].lower()


def test_e2e_authenticated_admin_opens_skills_and_memory_pages(hub: TestClient) -> None:
    client = hub
    bootstrap_admin(client)
    login = client.post(
        "/api/auth/login",
        json={"email": "owner@example.test", "password": "correct-horse"},
    )
    assert login.status_code == 200, login.text

    skills_page = client.get("/admin/skills")
    assert skills_page.status_code == 200, skills_page.text
    assert "Skill registry" in skills_page.text
    assert "/admin/memory" in skills_page.text
    assert "skill.record" in skills_page.text

    memory_page = client.get("/admin/memory")
    assert memory_page.status_code == 200, memory_page.text
    assert "Memory pods" in memory_page.text
    assert "/admin/skills" in memory_page.text
    assert "data-solidify" in memory_page.text

    listed = client.get("/api/registry/skills")
    assert listed.status_code == 200, listed.text
    assert "apply-workday" in {row["slug"] for row in listed.json()["skills"]}

    apply_a = invite_join(client, "application", "e2e-apply-ui")
    stored = client.post(
        "/api/memory/items",
        headers=bearer(apply_a["api_key"]),
        json=WORKDAY_QUIRK,
    )
    assert stored.status_code == 201, stored.text
    items = client.get("/api/memory/items", headers=bearer(apply_a["api_key"]))
    assert items.status_code == 200
    assert any(row["title"] == WORKDAY_QUIRK["title"] for row in items.json()["items"])
