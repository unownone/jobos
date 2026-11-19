"""Pagination, posting fields, and the operator home dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.constants import ROLES
from app.dashboard import summarize_dashboard
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


def test_posting_fields_roundtrip(client: TestClient) -> None:
    res = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={
            "id": "gh__pay1",
            "company": "Acme",
            "title": "Staff",
            "status": "discovered",
            "description": "Own the API platform.",
            "expectations": "Python + Postgres in production.",
            "pay": "$180k–$220k",
            "posted_at": "2026-03-01T00:00:00Z",
        },
    )
    assert res.status_code == 201, res.text
    job = res.json()["job"]
    assert job["description"].startswith("Own the API")
    assert "Postgres" in job["expectations"]
    assert job["pay"] == "$180k–$220k"
    assert job["posted_at"] == "2026-03-01T00:00:00Z"
    patched = client.patch(
        "/api/jobs/gh__pay1",
        headers=h("discovery"),
        json={"pay": "", "description": "Updated JD."},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["job"]["pay"] == ""
    assert patched.json()["job"]["description"] == "Updated JD."


def test_apply_cannot_rewrite_pay(client: TestClient) -> None:
    created = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={
            "id": "gh__pay2",
            "company": "Acme",
            "title": "Staff",
            "status": "apply_ready",
            "pay": "$1",
        },
    )
    job_id = created.json()["job"]["id"]
    denied = client.patch(f"/api/jobs/{job_id}", headers=h("apply"), json={"pay": "$999"})
    assert denied.status_code == 403


def test_list_jobs_paginates_and_filters(client: TestClient) -> None:
    for i in range(6):
        pay = f"${100 + i}k" if i % 2 == 0 else ""
        res = client.post(
            "/api/jobs",
            headers=h("discovery"),
            json={
                "id": f"page__{i}",
                "company": f"Co{i}",
                "title": "Engineer",
                "status": "discovered",
                "location": "Remote" if i < 3 else "NYC",
                "remote": True if i < 3 else False,
                "apply_kind": "ats" if i < 4 else "network",
                "sources": ["remoteok" if i < 3 else "dorks"],
                "score": 5 if i == 0 else 3,
                "pay": pay,
            },
        )
        assert res.status_code == 201, res.text
        if i < 2:
            moved = client.patch(
                f"/api/jobs/page__{i}",
                headers=h("apply"),
                json={"status": "applied"},
            )
            assert moved.status_code == 200, moved.text
    listed = client.get("/api/jobs?limit=2&offset=0", headers=h("admin"))
    body = listed.json()
    assert body["count"] == 2
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert body["matched"] == 6
    assert body["total"] == 6
    page2 = client.get("/api/jobs?limit=2&offset=2", headers=h("admin")).json()
    assert page2["count"] == 2
    assert page2["offset"] == 2
    ids = {row["id"] for row in body["jobs"]} | {row["id"] for row in page2["jobs"]}
    assert len(ids) == 4
    remote = client.get("/api/jobs?remote=remote&limit=50", headers=h("admin")).json()
    assert remote["matched"] == 3
    paid = client.get("/api/jobs?has_pay=true&limit=50", headers=h("admin")).json()
    assert paid["matched"] == 3
    kind = client.get("/api/jobs?apply_kind=network&limit=50", headers=h("admin")).json()
    assert kind["matched"] == 2
    scored = client.get("/api/jobs?score_min=5&limit=50", headers=h("admin")).json()
    assert scored["matched"] == 1
    lane = client.get("/api/jobs?lane=apply&limit=50", headers=h("admin")).json()
    assert lane["matched"] == 2
    loc = client.get("/api/jobs?location=NYC&limit=50", headers=h("admin")).json()
    assert loc["matched"] == 3
    # Omitting limit on this route applies 100 and reports that cap.
    full = client.get("/api/jobs", headers=h("admin")).json()
    assert full["limit"] == 100
    assert full["count"] == 6
    assert full["matched"] == 6
    assert len(full["jobs"]) == 6


def test_dashboard_funnel_today_and_oldest(client: TestClient) -> None:
    old_posted = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={
            "id": "dash__old",
            "company": "OldCo",
            "title": "Staff",
            "status": "discovered",
            "posted_at": old_posted,
            "pay": "$160k",
            "description": "Long-running req.",
        },
    )
    client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={"id": "dash__new", "company": "NewCo", "title": "Staff", "status": "apply_ready"},
    )
    client.patch("/api/jobs/dash__new", headers=h("apply"), json={"status": "applied"})
    client.patch(
        "/api/jobs/dash__new",
        headers=h("outreach"),
        json={"status": "outreaching"},
    )
    dash = client.get("/api/dashboard", headers=h("admin"))
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["funnel"]["found"] == 2
    assert body["funnel"]["applied"] == 1
    assert body["funnel"]["outreached"] == 1
    assert body["today"]["found"] == 2
    assert body["today"]["applied"] == 1
    oldest = body["oldest_in_pipeline"]
    assert oldest["id"] == "dash__old"
    assert oldest["posted_at"] == old_posted
    assert oldest["posted_known"] is True
    assert oldest["pay"] == "$160k"
    assert oldest["days_in_pipeline"] >= 39
    assert body["agents"]["total"] == 0
    assert body["agents"]["working"] >= 1
    assert body["agents"]["live"] >= 1
    page = client.get("/home", headers=h("admin"))
    assert page.status_code == 200
    assert "Hunt funnel" in page.text
    assert "/static/vendor/chart.umd.js" in page.text
    assert 'id="funnelLegend"' in page.text
    assert "chart-donut" in page.text


def test_summarize_dashboard_empty_board(tmp_path: Path) -> None:
    settings = Settings(
        board_dir=tmp_path,
        db_path=tmp_path / "empty.db",
        host="127.0.0.1",
        port=8787,
        tokens=dict(TOKENS),
    )
    client = TestClient(create_app(settings))
    db = client.app.state.db
    summary = summarize_dashboard(db, db.compat_tenant)
    assert summary["funnel"] == {"found": 0, "applied": 0, "outreached": 0}
    assert summary["oldest_in_pipeline"] is None
    assert summary["agents"]["working"] == 0
