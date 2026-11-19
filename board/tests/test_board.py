"""Hunt board API: auth, role write rules, events, hygiene."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.constants import ROLES
from app.db import BoardDB
from app.main import create_app
from app.settings import Settings
from app.storage.repos.jobs import SEARCH_CAP, _jobs_where
from app.tenant import TenantContext

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


def test_omitted_limit_reads_every_job_and_http_reports_the_cap(client: TestClient) -> None:
    db = client.app.state.db
    tenant = db.compat_tenant
    for i in range(101):
        db.insert_job(
            tenant,
            {
                "id": f"cap__{i:03d}",
                "company": f"Co{i}",
                "title": "Role",
                "apply_url": "https://example.test/dup" if i < 2 else "",
                "updated_at": (
                    "2020-01-01T00:00:00Z"
                    if i < 2
                    else f"2026-06-{(1 + (i // 60)):02d}T00:{(i % 60):02d}:00Z"
                ),
            },
        )
    assert len(db.list_jobs(tenant)) == 101
    assert len(db.list_jobs(tenant, limit=None)) == 101
    assert len(db.list_jobs(tenant, limit=100)) == 100
    assert db.count_jobs(tenant) == 101

    listed = client.get("/api/jobs", headers=h("admin"))
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["limit"] == 100
    assert body["count"] == 100
    assert body["matched"] == 101
    assert body["total"] == 101

    report = client.get("/api/hygiene", headers=h("maintenance"))
    assert report.status_code == 200, report.text
    duplicates = [
        item
        for item in report.json()["duplicate_apply_urls"]
        if item["apply_url"] == "https://example.test/dup"
    ]
    assert len(duplicates) == 1
    assert sorted(duplicates[0]["ids"]) == ["cap__000", "cap__001"]

    replaced = client.post(
        "/api/import",
        headers=h("admin"),
        json={
            "replace": True,
            "jobs": [
                {
                    "id": "import__kept",
                    "company": "Kept",
                    "title": "Only",
                    "status": "discovered",
                }
            ],
        },
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["created"] == 1
    after = client.get("/api/jobs", headers=h("admin")).json()
    assert after["total"] == 1
    assert [row["id"] for row in after["jobs"]] == ["import__kept"]


def test_job_search_caps_terms_and_escapes_wildcards(tmp_path: Path) -> None:
    tenant = TenantContext("acc_search")
    where, args = _jobs_where(tenant, q="100%_" + ("x" * 80))
    assert where.count("ESCAPE") == 10
    assert "LIKE ?" not in where
    assert args[0] == "acc_search"
    assert args[1] == "100\\%\\_" + ("x" * (SEARCH_CAP - len("100%_")))
    assert all(arg == args[1] for arg in args[1:])

    db = BoardDB(tmp_path / "board.db")
    tenant = db.compat_tenant
    try:
        db.insert_job(tenant, {"id": "wild__pct", "company": "100% Ready", "title": "Staff"})
        db.insert_job(tenant, {"id": "wild__plain", "company": "Acme", "title": "Staff", "notes": "A" * 48 + "TAIL"})
        db.insert_job(tenant, {"id": "wild__under", "company": "A_B", "title": "Staff"})
        db.insert_job(tenant, {"id": "wild__underx", "company": "AXB", "title": "Staff"})
        assert {row["id"] for row in db.list_jobs(tenant, q="%", limit=50)} == {"wild__pct"}
        assert {row["id"] for row in db.list_jobs(tenant, q="A_B", limit=50)} == {"wild__under"}
        assert {row["id"] for row in db.list_jobs(tenant, company="100%", limit=50)} == {"wild__pct"}
        capped = {row["id"] for row in db.list_jobs(tenant, q=("A" * 48) + "NOPE", limit=50)}
        assert "wild__plain" in capped
    finally:
        db.close()


def test_delete_jobs_for_account_removes_the_tenant_in_one_call(tmp_path: Path) -> None:
    db = BoardDB(tmp_path / "board.db")
    tenant = db.compat_tenant
    try:
        db.insert_job(tenant, {"id": "wipe__1", "company": "A", "title": "T"})
        db.insert_job(tenant, {"id": "wipe__2", "company": "B", "title": "T"})
        deleted = db.jobs.delete_jobs_for_account(tenant.account_id)
        assert deleted == 2
        assert db.list_jobs(tenant, limit=50) == []
    finally:
        db.close()


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
    assert "Select a job" not in res.text
    assert 'id="pager"' in res.text
    assert 'id="moreFilters"' in res.text
    home = client.get("/home", headers=h("admin"))
    assert home.status_code == 200
    assert "Hunt funnel" in home.text
    assert "Oldest open job" in home.text
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
