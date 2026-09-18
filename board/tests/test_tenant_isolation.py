"""Tenant isolation: accounts, jobs, blobs, queue routing."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        board_dir=tmp_path,
        db_path=tmp_path / "board.db",
        host="127.0.0.1",
        port=8787,
        tokens={"admin": "test-token-admin-not-real"},
        blob_adapter="memory",
        queue_adapter="memory",
        blob_root=tmp_path / "blobs",
    )


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(_settings(tmp_path)))


def test_landing_is_public(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "Find jobs" in res.text or "jobOS" in res.text
    assert "Select a job" not in res.text


def test_login_page_has_signup(client: TestClient) -> None:
    res = client.get("/login")
    assert res.status_code == 200
    assert "Create account" in res.text
    assert "Username" in res.text


def test_signup_login_and_isolation(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    alice = TestClient(app)
    bob = TestClient(app)

    a = alice.post("/api/auth/signup", json={"username": "alicehunt", "password": "s3cret-alice"})
    assert a.status_code == 200, a.text
    account_a = a.json()["account"]["id"]
    assert account_a.startswith("acc_")

    csrf_a = alice.cookies.get("hub_csrf") or ""
    job = alice.post(
        "/api/jobs",
        json={"id": "board__alice-role", "company": "AliceCo", "title": "Staff"},
        headers={"X-CSRF": csrf_a, "Content-Type": "application/json"},
    )
    assert job.status_code == 201, job.text

    listed_a = alice.get("/api/jobs")
    assert listed_a.status_code == 200
    assert any(j["company"] == "AliceCo" for j in listed_a.json()["jobs"])

    b = bob.post("/api/auth/signup", json={"username": "bobhuntx", "password": "s3cret-bobby"})
    assert b.status_code == 200, b.text
    assert b.json()["account"]["id"] != account_a

    listed_b = bob.get("/api/jobs")
    assert listed_b.status_code == 200, listed_b.text
    assert listed_b.json()["jobs"] == [] or all(
        j.get("company") != "AliceCo" for j in listed_b.json()["jobs"]
    )
    csrf_b = bob.cookies.get("hub_csrf") or ""
    stolen = bob.get("/api/jobs/board__alice-role", headers={"X-CSRF": csrf_b})
    assert stolen.status_code == 404

    pushed = alice.post(
        "/api/queue/push",
        json={"kind": "discovery.search", "payload": {"portal": "wellfound", "query": "alice-only"}},
        headers={"X-CSRF": csrf_a, "Content-Type": "application/json"},
    )
    assert pushed.status_code == 200, pushed.text
    alice_q = alice.get("/api/queue")
    assert alice_q.status_code == 200, alice_q.text
    assert any("alice-only" in str(item) for item in alice_q.json()["items"])
    bob_q = bob.get("/api/queue")
    assert bob_q.status_code == 200, bob_q.text
    assert all("alice-only" not in str(item) for item in bob_q.json()["items"])

    resume = alice.put(
        "/api/candidate/resume",
        content=b"%PDF-1.4 alice-bytes",
        headers={"X-CSRF": csrf_a, "Content-Type": "application/pdf"},
    )
    assert resume.status_code == 200, resume.text
    alice_pdf = alice.get("/api/candidate/resume")
    assert alice_pdf.status_code == 200
    assert b"alice-bytes" in alice_pdf.content
    bob_pdf = bob.get("/api/candidate/resume")
    assert bob_pdf.status_code in {404, 409} or b"alice-bytes" not in bob_pdf.content

    login = alice.post(
        "/api/auth/login",
        json={"username": "alicehunt", "password": "s3cret-alice"},
    )
    assert login.status_code == 200, login.text


def test_account_service_rejects_short_password(tmp_path: Path, client: TestClient) -> None:
    res = client.post("/api/auth/signup", json={"username": "shorty", "password": "nope"})
    assert res.status_code == 422
