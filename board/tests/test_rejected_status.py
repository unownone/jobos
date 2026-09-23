"""Shared rejected status + company/user remarks. Any patch role may set it."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.constants import REJECTION_BY
from app.main import create_app
from app.settings import Settings

TOKENS = {
    "discovery": "test-token-discovery-not-real",
    "apply": "test-token-apply-not-real",
    "outreach": "test-token-outreach-not-real",
    "admin": "test-token-admin-not-real",
    "maintenance": "test-token-maintenance-not-real",
}


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


def _create(client: TestClient, job_id: str, status: str = "apply_ready") -> str:
    res = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={
            "id": job_id,
            "company": "Acme",
            "title": "Staff",
            "status": status,
            "sources": ["dorks"],
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["job"]["id"]


def test_schema_and_meta_advertise_rejected(client: TestClient) -> None:
    meta = client.get("/api/meta", headers=h("apply")).json()
    assert "rejected" in meta["statuses"]
    assert meta["shared_statuses"] == ["rejected"]
    assert meta["rejection_by"] == list(REJECTION_BY)
    caps = meta["capabilities"]
    assert "rejected" in caps["status_lane"]
    assert "rejection" in caps["patch_fields"]
    assert caps["shared_statuses"] == ["rejected"]


def test_apply_rejects_with_company_remarks(client: TestClient) -> None:
    job_id = _create(client, "rej__apply")
    res = client.patch(
        f"/api/jobs/{job_id}",
        headers=h("apply"),
        json={
            "status": "rejected",
            "rejection": {"by": "company", "remarks": "Went with another candidate"},
        },
    )
    assert res.status_code == 200, res.text
    job = res.json()["job"]
    assert job["status"] == "rejected"
    assert job["rejection"]["by"] == "company"
    assert job["rejection"]["company_remarks"] == "Went with another candidate"
    assert job["rejection"]["user_remarks"] == ""


def test_outreach_rejects_with_user_remarks(client: TestClient) -> None:
    job_id = _create(client, "rej__out")
    client.patch(f"/api/jobs/{job_id}", headers=h("apply"), json={"status": "applied"})
    res = client.patch(
        f"/api/jobs/{job_id}",
        headers=h("outreach"),
        json={
            "status": "rejected",
            "rejection": {"by": "user", "user_remarks": "I do not want this team"},
        },
    )
    assert res.status_code == 200, res.text
    job = res.json()["job"]
    assert job["status"] == "rejected"
    assert job["rejection"]["by"] == "user"
    assert job["rejection"]["user_remarks"] == "I do not want this team"


def test_discovery_rejects_in_lane(client: TestClient) -> None:
    job_id = _create(client, "rej__disc", status="discovered")
    res = client.patch(
        f"/api/jobs/{job_id}",
        headers=h("discovery"),
        json={
            "status": "rejected",
            "rejection": {"by": "user", "remarks": "deal-breaker: on-site 5 days"},
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["job"]["status"] == "rejected"
    assert res.json()["job"]["rejection"]["user_remarks"] == "deal-breaker: on-site 5 days"


def test_discovery_can_reject_after_apply_lane(client: TestClient) -> None:
    job_id = _create(client, "rej__late")
    moved = client.patch(f"/api/jobs/{job_id}", headers=h("apply"), json={"status": "applying"})
    assert moved.status_code == 200, moved.text
    still_blocked = client.patch(
        f"/api/jobs/{job_id}",
        headers=h("discovery"),
        json={"score": 5},
    )
    assert still_blocked.status_code == 403
    res = client.patch(
        f"/api/jobs/{job_id}",
        headers=h("discovery"),
        json={
            "status": "rejected",
            "company": "Acme",
            "title": "Staff",
            "rejection": {"by": "company", "company_remarks": "Req closed"},
        },
    )
    assert res.status_code == 200, res.text
    job = res.json()["job"]
    assert job["status"] == "rejected"
    assert job["rejection"]["by"] == "company"
    assert job["rejection"]["company_remarks"] == "Req closed"
    assert job["score"] is None


def test_rejected_requires_by(client: TestClient) -> None:
    job_id = _create(client, "rej__noby")
    res = client.patch(
        f"/api/jobs/{job_id}",
        headers=h("apply"),
        json={"status": "rejected"},
    )
    assert res.status_code == 422
    bad_by = client.patch(
        f"/api/jobs/{job_id}",
        headers=h("apply"),
        json={"status": "rejected", "rejection": {"by": "recruiter"}},
    )
    assert bad_by.status_code == 422


def test_create_rejected_requires_by(client: TestClient) -> None:
    missing = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={"id": "rej__create-bad", "company": "No", "title": "X", "status": "rejected"},
    )
    assert missing.status_code == 422
    ok = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={
            "id": "rej__create-ok",
            "company": "NoCo",
            "title": "Skip",
            "status": "rejected",
            "sources": ["user"],
            "rejection": {"by": "user", "remarks": "already spoke to them"},
        },
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["job"]["rejection"]["user_remarks"] == "already spoke to them"


def test_search_matches_rejection_remarks(client: TestClient) -> None:
    job_id = _create(client, "rej__search")
    client.patch(
        f"/api/jobs/{job_id}",
        headers=h("apply"),
        json={
            "status": "rejected",
            "rejection": {"by": "company", "remarks": "unique-zebra-token"},
        },
    )
    listed = client.get("/api/jobs", headers=h("admin"), params={"q": "unique-zebra-token"})
    assert listed.status_code == 200
    ids = [row["id"] for row in listed.json()["jobs"]]
    assert job_id in ids


def test_rejected_is_not_open_pipeline(client: TestClient) -> None:
    job_id = _create(client, "rej__pipe", status="discovered")
    client.patch(
        f"/api/jobs/{job_id}",
        headers=h("discovery"),
        json={"status": "rejected", "rejection": {"by": "user", "remarks": "no"}},
    )
    dash = client.get("/api/dashboard", headers=h("admin")).json()
    assert dash["oldest_in_pipeline"] is None
    assert dash["funnel"]["found"] == 1
    assert dash["funnel"]["applied"] == 0


def test_new_jobs_have_empty_rejection(client: TestClient) -> None:
    job_id = _create(client, "rej__empty", status="discovered")
    job = client.get(f"/api/jobs/{job_id}", headers=h("discovery")).json()["job"]
    assert job["rejection"] == {"by": "", "company_remarks": "", "user_remarks": ""}
