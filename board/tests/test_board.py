"""Hunt board API: auth, role write rules, events, hygiene."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.constants import ROLES
from app.main import create_app
from app.settings import Settings

TOKENS = {role: f"test-token-{role}-not-real" for role in ROLES}


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        board_dir=tmp_path,
        db_path=tmp_path / "board.db",
        host="127.0.0.1",
        port=8787,
        tokens=dict(TOKENS),
    )
    return TestClient(create_app(settings))


def h(role: str, actor: str = "pytest") -> dict[str, str]:
    return {"X-Role": role, "X-Token": TOKENS[role], "X-Actor": actor}


def test_health_is_public(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "admin_bootstrapped" in body


def test_api_requires_headers(client: TestClient) -> None:
    res = client.get("/api/jobs")
    assert res.status_code == 401


def test_wrong_token_rejected(client: TestClient) -> None:
    res = client.get("/api/jobs", headers={"X-Role": "admin", "X-Token": "nope"})
    assert res.status_code == 401


def test_token_does_not_work_for_other_role(client: TestClient) -> None:
    res = client.get("/api/jobs", headers={"X-Role": "admin", "X-Token": TOKENS["discovery"]})
    assert res.status_code == 401


def test_discovery_creates_and_lists(client: TestClient) -> None:
    res = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={
            "id": "remoteok__999",
            "company": "Acme",
            "title": "Staff Engineer",
            "apply_url": "https://jobs.example.com/staff",
            "sources": ["remoteok"],
            "status": "apply_ready",
            "score": 4,
            "apply_packet": {"url": "https://jobs.example.com/staff", "steps": ["Open URL"]},
        },
    )
    assert res.status_code == 201, res.text
    job = res.json()["job"]
    assert job["status"] == "apply_ready"
    listed = client.get("/api/jobs", headers=h("apply"))
    body = listed.json()
    assert body["count"] == 1
    assert body["total"] == 1


def test_discovery_cannot_create_apply_lane_status(client: TestClient) -> None:
    res = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={"company": "Acme", "title": "X", "status": "applying"},
    )
    assert res.status_code == 403


def test_maintenance_cannot_create(client: TestClient) -> None:
    res = client.post(
        "/api/jobs",
        headers=h("maintenance"),
        json={"company": "Acme", "title": "X"},
    )
    assert res.status_code == 403


def test_duplicate_apply_url_conflict(client: TestClient) -> None:
    body = {
        "company": "Acme",
        "title": "One",
        "apply_url": "https://jobs.example.com/dup",
        "sources": ["dorks"],
    }
    assert client.post("/api/jobs", headers=h("discovery"), json=body).status_code == 201
    second = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={**body, "title": "Two"},
    )
    assert second.status_code == 409


def test_apply_patches_apply_fields_only(client: TestClient) -> None:
    created = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={
            "id": "gh__1",
            "company": "Acme",
            "title": "Staff",
            "status": "apply_ready",
            "apply_packet": {"url": "https://example.com", "steps": ["go"]},
        },
    )
    job_id = created.json()["job"]["id"]
    forbidden = client.patch(
        f"/api/jobs/{job_id}",
        headers=h("apply"),
        json={"company": "Hacked"},
    )
    assert forbidden.status_code == 403
    ok = client.patch(
        f"/api/jobs/{job_id}",
        headers=h("apply"),
        json={
            "status": "applied",
            "owners": {"apply": "apply-bot"},
            "proof": {"submitted_at": "2026-09-06T18:00:00Z", "confirmation": "ok"},
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["job"]["status"] == "applied"
    assert ok.json()["job"]["company"] == "Acme"


def test_outreach_cannot_rewrite_apply_url(client: TestClient) -> None:
    created = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={
            "id": "gh__2",
            "company": "Acme",
            "title": "Staff",
            "status": "apply_ready",
            "apply_url": "https://example.com/a",
        },
    )
    job_id = created.json()["job"]["id"]
    client.patch(f"/api/jobs/{job_id}", headers=h("apply"), json={"status": "applied"})
    res = client.patch(
        f"/api/jobs/{job_id}",
        headers=h("outreach"),
        json={"apply_url": "https://evil.example"},
    )
    assert res.status_code == 403


def test_discovery_cannot_patch_after_apply_lane(client: TestClient) -> None:
    created = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={"id": "gh__3", "company": "Acme", "title": "Staff", "status": "apply_ready"},
    )
    job_id = created.json()["job"]["id"]
    client.patch(f"/api/jobs/{job_id}", headers=h("apply"), json={"status": "applying"})
    res = client.patch(
        f"/api/jobs/{job_id}",
        headers=h("discovery"),
        json={"score": 5},
    )
    assert res.status_code == 403


def test_discovery_can_patch_discovery_fields_in_lane(client: TestClient) -> None:
    created = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={"id": "gh__4", "company": "Acme", "title": "Staff", "status": "discovered"},
    )
    job_id = created.json()["job"]["id"]
    res = client.patch(
        f"/api/jobs/{job_id}",
        headers=h("discovery"),
        json={"status": "apply_ready", "score": 5, "apply_packet": {"steps": ["open"]}},
    )
    assert res.status_code == 200, res.text
    assert res.json()["job"]["score"] == 5


def test_admin_stop_freezes_job(client: TestClient) -> None:
    created = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={"id": "gh__5", "company": "Acme", "title": "Staff", "status": "apply_ready"},
    )
    job_id = created.json()["job"]["id"]
    stop = client.post(
        f"/api/jobs/{job_id}/stop",
        headers=h("admin"),
        json={"reason": "duplicate of gh__1"},
    )
    assert stop.status_code == 200
    assert stop.json()["job"]["stopped"] is True
    frozen = client.patch(
        f"/api/jobs/{job_id}",
        headers=h("apply"),
        json={"status": "applying"},
    )
    assert frozen.status_code == 409


def test_non_admin_cannot_stop_or_delete(client: TestClient) -> None:
    created = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={"id": "gh__6", "company": "Acme", "title": "Staff"},
    )
    job_id = created.json()["job"]["id"]
    assert client.post(
        f"/api/jobs/{job_id}/stop",
        headers=h("discovery"),
        json={"reason": "nope"},
    ).status_code == 403
    assert client.delete(f"/api/jobs/{job_id}", headers=h("apply")).status_code == 403
    assert client.delete(f"/api/jobs/{job_id}", headers=h("admin")).status_code == 200


def test_events_are_appended(client: TestClient) -> None:
    client.post(
        "/api/jobs",
        headers=h("discovery", "disc-1"),
        json={"id": "gh__7", "company": "Acme", "title": "Staff"},
    )
    events = client.get("/api/events", headers=h("maintenance")).json()["events"]
    assert events
    assert events[0]["action"] == "create"
    assert events[0]["actor_role"] == "discovery"


def test_unknown_status_rejected(client: TestClient) -> None:
    res = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={"company": "Acme", "title": "Staff", "status": "wishlist"},
    )
    assert res.status_code == 422


def test_maintenance_hygiene_and_import(client: TestClient) -> None:
    assert client.get("/api/hygiene", headers=h("discovery")).status_code == 403
    report = client.get("/api/hygiene", headers=h("maintenance"))
    assert report.status_code == 200
    imported = client.post(
        "/api/import",
        headers=h("maintenance"),
        json={
            "jobs": [
                {
                    "id": "import__one",
                    "company": "ImportedCo",
                    "title": "Engineer",
                    "status": "discovered",
                    "sources": ["ledger"],
                }
            ]
        },
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["created"] == 1
    replace = client.post(
        "/api/import",
        headers=h("maintenance"),
        json={"jobs": [], "replace": True},
    )
    assert replace.status_code == 403


def test_ui_is_served(client: TestClient) -> None:
    landing = client.get("/")
    assert landing.status_code == 200
    assert "jobOS" in landing.text
    denied = client.get("/board")
    assert denied.status_code == 401
    assert "Select a job" not in denied.text
    res = client.get("/board", headers=h("admin"))
    assert res.status_code == 200
    assert "jobOS Harness" in res.text
    assert "helps find jobs" in res.text
    assert "All statuses" in res.text
    assert "Select a job" in res.text
    assert 'id="connectForm"' not in res.text
    assert "Connect</button>" not in res.text


def test_env_example_has_empty_placeholders() -> None:
    example = Path(__file__).resolve().parents[1] / ".env.example"
    text = example.read_text(encoding="utf-8")
    for name in (
        "BOARD_TOKEN_DISCOVERY",
        "BOARD_TOKEN_APPLY",
        "BOARD_TOKEN_OUTREACH",
        "BOARD_TOKEN_ADMIN",
        "BOARD_TOKEN_MAINTENANCE",
    ):
        assert f"{name}=" in text
        for line in text.splitlines():
            if line.startswith(name + "="):
                assert line.split("=", 1)[1] == ""
        assert "sk-" not in text
        gitignore = Path(__file__).resolve().parents[1] / ".gitignore"
        gi = gitignore.read_text(encoding="utf-8")
        assert ".env" in gi
        assert "tokens.local.json" in gi
def test_readme_screenshots_exist() -> None:
    docs = Path(__file__).resolve().parents[1] / "docs"
    for name in ("01-dashboard.png", "02-filters.png", "03-detail.png"):
        path = docs / name
        assert path.is_file(), path
        assert path.stat().st_size > 1000
