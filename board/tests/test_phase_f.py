"""Phase F: people API, ledger export, catalog 7-day gate, resume, compat deprecation."""

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
        packs_dir=tmp_path / "packs",
    )


@pytest.fixture()
def hub(tmp_path: Path) -> tuple[TestClient, Settings]:
    settings = _settings(tmp_path)
    return TestClient(create_app(settings)), settings


def h(role: str, actor: str = "pytest") -> dict[str, str]:
    return {"X-Role": role, "X-Token": TOKENS[role], "X-Actor": actor}


def test_compat_whoami_is_deprecated(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    who = client.get("/api/whoami", headers=h("apply"))
    assert who.status_code == 200
    body = who.json()
    assert body["compat"] is True
    assert body["compat_deprecated"] is True
    assert "Bearer" in body["deprecation"]


def test_discovery_cannot_mark_applied(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    created = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={
            "id": "remoteok__no-easy-apply",
            "company": "Acme",
            "title": "Staff",
            "status": "apply_ready",
            "apply_packet": {"url": "https://example.com", "steps": ["open"]},
        },
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["job"]["id"]
    denied = client.patch(
        f"/api/jobs/{job_id}",
        headers=h("discovery"),
        json={"status": "applied"},
    )
    assert denied.status_code == 403


def test_people_round_trip_and_export(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    created = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={
            "id": "remoteok__people-job",
            "company": "Acme",
            "title": "Staff Engineer",
            "status": "apply_ready",
            "notes": "do not copy BOARD_TOKEN_DISCOVERY into git",
            "apply_packet": {"url": "https://example.com/staff", "steps": ["Open"]},
        },
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["job"]["id"]
    denied = client.get("/api/people", headers=h("discovery"))
    assert denied.status_code == 403
    posted = client.post(
        "/api/people",
        headers=h("outreach"),
        json={
            "id": "acme__jordan-lee",
            "name": "Jordan Lee",
            "title": "Engineering Manager",
            "company": "Acme",
            "job_id": job_id,
            "linkedin_url": "https://www.linkedin.com/in/example",
            "email": "",
            "do_not_contact": False,
            "touches": [],
        },
    )
    assert posted.status_code == 201, posted.text
    person_id = posted.json()["person"]["id"]
    patched = client.patch(
        f"/api/people/{person_id}",
        headers=h("outreach"),
        json={"title": "Director of Engineering"},
    )
    assert patched.status_code == 200
    listed = client.get("/api/people", headers=h("admin"), params={"job_id": job_id})
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    secret = client.post(
        "/api/people",
        headers=h("outreach"),
        json={"name": "Nope", "api_key": "jh_agt_nope"},
    )
    assert secret.status_code == 422

    exported = client.get("/api/export/ledger", headers=h("admin"), params={"format": "json"})
    assert exported.status_code == 200, exported.text
    body = exported.json()
    assert any(p["id"] == person_id for p in body["people"])
    assert any("people/" in path for path in body["files"])
    blob = str(body)
    assert "BOARD_TOKEN" not in blob
    assert "blob_encrypted" not in blob
    tar = client.get("/api/export/ledger", headers=h("maintenance"), params={"format": "tar"})
    assert tar.status_code == 200
    assert tar.headers["content-type"].startswith("application/gzip")
    forbidden = client.get("/api/export/ledger", headers=h("discovery"))
    assert forbidden.status_code == 403


def test_stale_catalog_blocks_discovery_search(hub: tuple[TestClient, Settings], monkeypatch: pytest.MonkeyPatch) -> None:
    client, _settings = hub
    monkeypatch.setattr("app.queue.catalog_fresh_enough", lambda *args, **kwargs: False)
    pushed = client.post(
        "/api/queue/push",
        headers=h("discovery"),
        json={"kind": "discovery.search", "payload": {"portal": "remoteok", "query": "staff"}},
    )
    assert pushed.status_code == 200, pushed.text
    blocked = client.post(
        "/api/queue/claim",
        headers=h("discovery"),
        json={"kinds": ["discovery.search"], "limit": 1},
    )
    assert blocked.status_code == 409
    assert "catalog" in blocked.json()["detail"]


def test_catalog_refresh_ack_unlocks_search(hub: tuple[TestClient, Settings], monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timezone

    from app.queue import catalog_date_is_fresh, catalog_refresh_acked_recent

    assert catalog_date_is_fresh("2019-01-01", datetime(2026, 9, 7, tzinfo=timezone.utc)) is False
    assert catalog_date_is_fresh("2026-09-06", datetime(2026, 9, 7, tzinfo=timezone.utc)) is True

    client, _settings = hub
    monkeypatch.setattr("app.queue.catalog_date_is_fresh", lambda *args, **kwargs: False)
    pushed = client.post(
        "/api/queue/push",
        headers=h("maintenance"),
        json={"kind": "catalog.refresh", "payload": {"reason": "stale"}},
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
    assert catalog_refresh_acked_recent(client.app.state.db) is True

    client.post(
        "/api/queue/push",
        headers=h("discovery"),
        json={"kind": "discovery.search", "payload": {"portal": "wellfound", "query": "ml"}},
    )
    claimed_search = client.post(
        "/api/queue/claim",
        headers=h("discovery"),
        json={"kinds": ["discovery.search"], "limit": 1},
    )
    assert claimed_search.status_code == 200, claimed_search.text
    assert claimed_search.json()["count"] == 1


@pytest.mark.no_candidate
def test_candidate_public_false_and_resume_gates(hub: tuple[TestClient, Settings]) -> None:
    client, settings = hub
    public = client.get("/api/candidate/public", headers=h("discovery"))
    assert public.status_code == 200
    assert public.json()["present"] is False
    missing = client.get("/api/candidate/resume", headers=h("apply"))
    assert missing.status_code == 404
    denied = client.get("/api/candidate/resume", headers=h("discovery"))
    assert denied.status_code == 403
    uploaded = client.put(
        "/api/candidate/resume",
        headers=h("admin"),
        content=b"%PDF-1.4 test resume",
    )
    assert uploaded.status_code == 200, uploaded.text
    ok = client.get("/api/candidate/resume", headers=h("outreach"))
    assert ok.status_code == 200
    assert ok.content.startswith(b"%PDF")
    still_denied = client.get("/api/candidate/resume", headers=h("discovery"))
    assert still_denied.status_code == 403
    assert not (settings.board_dir.parent / "profiles" / "candidate.yaml").exists()
