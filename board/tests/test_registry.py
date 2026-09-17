"""Skill registry: GitHub seed, local forks, maintainer proctor queue."""

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
    client.cookies.clear()
    return keys


def test_github_starters_seed_on_boot(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    res = client.get("/api/registry/skills", headers=h("discovery"))
    assert res.status_code == 200, res.text
    slugs = {row["slug"] for row in res.json()["skills"]}
    assert "job-discovery" in slugs
    assert "job-apply" in slugs
    assert "job-outreach" in slugs
    assert "skill-maintainer" in slugs
    assert "compose-outreach" in slugs
    assert "playwright-cli-skill" in slugs
    assert "apply-workday" in slugs
    assert "source-indeed" in slugs
    assert "outreach-email" in slugs
    discovery = next(row for row in res.json()["skills"] if row["slug"] == "job-discovery")
    assert discovery["scope"] == "shared"
    assert discovery["status"] == "approved"
    assert discovery["origin"] == "github"
    assert "source" in discovery["tags"]


def test_mcp_registry_seeded_on_boot(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    res = client.get("/api/registry/mcps", headers=h("discovery"))
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["count"] > 0
    slugs = {row["slug"] for row in payload["mcps"]}
    assert "exa-mcp" in slugs
    assert "gmail-mcp" in slugs
    assert "indeed-mcp" in slugs
    assert "playwright-mcp" in slugs
    adopted = client.get(
        "/api/registry/mcps",
        headers=h("discovery"),
        params={"status": "adopted", "kind": "mcp"},
    )
    assert adopted.status_code == 200
    assert adopted.json()["count"] > 0
    assert all(row["kind"] == "mcp" and row["status"] == "adopted" for row in adopted.json()["mcps"])
    one = client.get("/api/registry/mcps/exa-mcp", headers=h("discovery"))
    assert one.status_code == 200, one.text
    mcp = one.json()["mcp"]
    assert mcp["id"] == "mcp_exa-mcp"
    assert mcp["origin"] == "github"
    assert mcp["status"] == "adopted"
    assert mcp["config"]
    rejected = client.get(
        "/api/registry/mcps",
        headers=h("discovery"),
        params={"status": "rejected", "kind": "mcp"},
    )
    assert rejected.json()["count"] > 0


def test_registry_seed_upsert_is_idempotent(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    maint_keys = mint_track_agents(client, "maintenance", ["maint-seed-idemp"])
    skills = client.get("/api/registry/skills", headers=bearer(maint_keys[0]))
    mcps = client.get("/api/registry/mcps", headers=bearer(maint_keys[0]))
    assert skills.json()["count"] > 0
    assert mcps.json()["count"] > 0
    skill_ids = sorted(row["id"] for row in skills.json()["skills"])
    mcp_ids = sorted(row["id"] for row in mcps.json()["mcps"])
    seeded = client.post("/api/registry/seed", headers=bearer(maint_keys[0]))
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["skills"]["inserted"] == 0
    assert seeded.json()["mcps"]["inserted"] == 0
    again_skills = client.get("/api/registry/skills", headers=bearer(maint_keys[0]))
    again_mcps = client.get("/api/registry/mcps", headers=bearer(maint_keys[0]))
    assert sorted(row["id"] for row in again_skills.json()["skills"]) == skill_ids
    assert sorted(row["id"] for row in again_mcps.json()["mcps"]) == mcp_ids
    assert again_skills.json()["count"] == skills.json()["count"]
    assert again_mcps.json()["count"] == mcps.json()["count"]


def test_meta_lists_skill_record_kind(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    res = client.get("/api/meta", headers=h("discovery"))
    assert res.status_code == 200
    assert "skill.record" in res.json()["queue_kinds"]
    assert res.json()["registry"] == "/api/registry/skills"
    assert res.json()["mcp_registry"] == "/api/registry/mcps"


def test_local_skill_is_invisible_to_other_bots(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    apply_keys = mint_track_agents(client, "application", ["apply-a", "apply-b"])
    created = client.post(
        "/api/registry/skills",
        headers=bearer(apply_keys[0]),
        json={
            "slug": "apply-obscure-board",
            "name": "Obscure board apply",
            "role": "apply",
            "tags": ["apply", "ats"],
            "platform": "custom",
            "match": {"ats": ["custom"], "url_patterns": ["*.obscure.test/*"], "apply_kind": ["ats"]},
            "inputs": ["job", "apply_packet"],
            "outputs": ["proof"],
            "body": "Fill the custom ATS. Same steps for every job on this host.",
        },
    )
    assert created.status_code == 200, created.text
    skill = created.json()["skill"]
    assert skill["scope"] == "local"
    assert skill["origin"] == "mutation"
    mine = client.get("/api/registry/skills", headers=bearer(apply_keys[0]))
    assert skill["id"] in {row["id"] for row in mine.json()["skills"]}
    other = client.get("/api/registry/skills", headers=bearer(apply_keys[1]))
    assert skill["id"] not in {row["id"] for row in other.json()["skills"]}
    stolen = client.get(f"/api/registry/skills/{skill['id']}", headers=bearer(apply_keys[1]))
    assert stolen.status_code == 404
    patch = client.patch(
        f"/api/registry/skills/{skill['id']}",
        headers=bearer(apply_keys[1]),
        json={"body": "hijack"},
    )
    assert patch.status_code in {403, 404}


def test_fork_shared_then_submit_recording_maintainer_only_consumes(
    hub: tuple[TestClient, Settings],
) -> None:
    client, _ = hub
    apply_keys = mint_track_agents(client, "application", ["apply-c"])
    maint_keys = mint_track_agents(client, "maintenance", ["maint-a"])
    listed = client.get("/api/registry/skills?tag=apply", headers=bearer(apply_keys[0]))
    shared = next(row for row in listed.json()["skills"] if row["slug"] == "job-apply")
    forked = client.post(
        f"/api/registry/skills/{shared['id']}/fork",
        headers=bearer(apply_keys[0]),
    )
    assert forked.status_code == 200, forked.text
    local = forked.json()["skill"]
    assert local["scope"] == "local"
    assert local["parent_skill_id"] == shared["id"]
    patched = client.patch(
        f"/api/registry/skills/{local['id']}",
        headers=bearer(apply_keys[0]),
        json={"body": local["body"] + "\n\nWorkday: always confirm the req id field before submit."},
    )
    assert patched.status_code == 200, patched.text
    submitted = client.post(
        "/api/registry/recordings",
        headers=bearer(apply_keys[0]),
        json={"skill_id": local["id"], "note": "generalized workday req-id check"},
    )
    assert submitted.status_code == 200, submitted.text
    recording_id = submitted.json()["recording"]["id"]
    queue_id = submitted.json()["queue_item"]["id"]

    denied = client.post(
        "/api/queue/claim",
        headers=bearer(apply_keys[0]),
        json={"kinds": ["skill.record"]},
    )
    assert denied.status_code == 403

    claimed = client.post(
        "/api/queue/claim",
        headers=bearer(maint_keys[0]),
        json={"kinds": ["skill.record"]},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["count"] == 1
    assert claimed.json()["items"][0]["id"] == queue_id

    too_soon = client.post(
        f"/api/registry/recordings/{recording_id}/promote",
        headers=bearer(maint_keys[0]),
    )
    assert too_soon.status_code == 409

    proctor = client.post(
        f"/api/registry/recordings/{recording_id}/proctor",
        headers=bearer(maint_keys[0]),
        json={"verdict": "pass", "note": "reproducible workday check"},
    )
    assert proctor.status_code == 200, proctor.text
    promoted = client.post(
        f"/api/registry/recordings/{recording_id}/promote",
        headers=bearer(maint_keys[0]),
    )
    assert promoted.status_code == 200, promoted.text
    skill = promoted.json()["skill"]
    assert skill["scope"] == "shared"
    assert skill["status"] == "approved"
    assert skill["origin"] == "recording"
    assert "req id" in skill["body"]

    discovery_keys = mint_track_agents(client, "discovery", ["disc-reg"])
    visible = client.get("/api/registry/skills", headers=bearer(discovery_keys[0]))
    slugs = {row["slug"]: row for row in visible.json()["skills"]}
    assert slugs["job-apply"]["origin"] == "recording"


def test_apply_can_push_skill_record_but_not_claim(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    apply_keys = mint_track_agents(client, "application", ["apply-push"])
    created = client.post(
        "/api/registry/skills",
        headers=bearer(apply_keys[0]),
        json={
            "slug": "apply-greenhouse-local",
            "name": "Greenhouse local",
            "role": "apply",
            "tags": ["apply", "greenhouse"],
            "body": "Use the greenhouse packet steps for every greenhouse URL.",
        },
    )
    assert created.status_code == 200, created.text
    submitted = client.post(
        "/api/registry/recordings",
        headers=bearer(apply_keys[0]),
        json={"skill_id": created.json()["skill"]["id"]},
    )
    assert submitted.status_code == 200, submitted.text
    listed = client.get("/api/queue?kind=skill.record", headers=h("admin"))
    kinds = {row["kind"] for row in listed.json()["items"]}
    assert "skill.record" in kinds


def test_match_url_filters_workday(hub: tuple[TestClient, Settings]) -> None:
    client, _ = hub
    apply_keys = mint_track_agents(client, "application", ["apply-match"])
    client.post(
        "/api/registry/skills",
        headers=bearer(apply_keys[0]),
        json={
            "slug": "apply-workday-local",
            "name": "Workday local",
            "role": "apply",
            "tags": ["apply", "workday"],
            "platform": "workday",
            "match": {
                "ats": ["workday"],
                "url_patterns": ["*.myworkdayjobs.com/*"],
                "apply_kind": ["ats"],
            },
            "body": "Workday apply: open the URL, confirm req id, upload PDF.",
        },
    )
    hit = client.get(
        "/api/registry/skills",
        headers=bearer(apply_keys[0]),
        params={"ats": "workday", "url": "https://acme.myworkdayjobs.com/en-US/job/1"},
    )
    assert hit.status_code == 200
    slugs = {row["slug"] for row in hit.json()["skills"]}
    assert "apply-workday-local" in slugs
    miss = client.get(
        "/api/registry/skills",
        headers=bearer(apply_keys[0]),
        params={"url": "https://boards.greenhouse.io/acme/jobs/1"},
    )
    miss_slugs = {row["slug"] for row in miss.json()["skills"]}
    assert "apply-workday-local" not in miss_slugs
