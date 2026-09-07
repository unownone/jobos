"""Metrics store + token-burn API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.constants import ROLES
from app.main import create_app
from app.metrics import percentile
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


def test_percentile() -> None:
    assert percentile([], 50) is None
    assert percentile([10], 95) == 10
    assert percentile([1, 2, 3, 4], 50) == 2.5


def test_any_role_can_log_token_burn(client: TestClient) -> None:
    res = client.post(
        "/api/metrics/token_burn",
        headers=h("discovery"),
        json={
            "tool_name": "exa-mcp",
            "skill": "discovery",
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "duration_ms": 12.5,
            "job_id": "gh__1",
        },
    )
    assert res.status_code == 201, res.text
    row = res.json()["row"]
    assert row["total_tokens"] == 120
    assert row["actor_role"] == "discovery"


def test_metrics_summary_is_maintainer_only(client: TestClient) -> None:
    client.post(
        "/api/metrics/token_burn",
        headers=h("apply"),
        json={"tool_name": "job-apply", "skill": "apply", "prompt_tokens": 50},
    )
    assert client.get("/api/metrics/summary", headers=h("apply")).status_code == 403
    summary = client.get("/api/metrics/summary", headers=h("maintenance"))
    assert summary.status_code == 200
    body = summary.json()
    assert body["n"] == 1
    assert body["totals"]["total_tokens"] == 50
    assert body["by_tool"][0]["name"] == "job-apply"


def test_pause_freezes_without_closing(client: TestClient) -> None:
    created = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={"id": "gh__pause", "company": "Acme", "title": "Staff", "status": "apply_ready"},
    )
    job_id = created.json()["job"]["id"]
    paused = client.post(
        f"/api/jobs/{job_id}/pause",
        headers=h("admin"),
        json={"reason": "human review"},
    )
    assert paused.status_code == 200, paused.text
    job = paused.json()["job"]
    assert job["stopped"] is True
    assert job["status"] == "apply_ready"
    frozen = client.patch(
        f"/api/jobs/{job_id}",
        headers=h("apply"),
        json={"status": "applying"},
    )
    assert frozen.status_code == 409
    resumed = client.post(f"/api/jobs/{job_id}/resume", headers=h("admin"))
    assert resumed.status_code == 200
    assert resumed.json()["job"]["stopped"] is False
    ok = client.patch(
        f"/api/jobs/{job_id}",
        headers=h("apply"),
        json={"status": "applying"},
    )
    assert ok.status_code == 200
