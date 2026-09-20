"""E2E: cookieless agent join after the operator tenant is onboarded.

Production agents POST /api/auth/join with invite_id + s and no session.
Existing TestClient suites bootstrap_admin on the same client, so cookies make
the candidate gate look at the operator tenant. This file uses a second client
with an empty cookie jar — the real agent path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.constants import ROLES
from app.identity import create_invite
from app.main import create_app
from app.profile import hub_candidate_path, hub_resume_path
from app.settings import Settings

TOKENS = {role: f"test-token-{role}-not-real" for role in ROLES}

ONBOARDED_CANDIDATE = {
    "identity": {
        "full_name": "Jordan Lee",
        "email": "jordan@example.test",
        "location": "Remote",
        "work_authorization": "US citizen",
    },
    "target": {
        "titles": ["Staff Software Engineer"],
        "locations": ["Remote"],
        "deal_breakers": ["Unpaid trials"],
    },
    "proof": {"headline": "Ships backends", "highlights": ["Owns a service"]},
}

MINIMAL_PDF = (
    b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<</Type/Catalog>>endobj\ntrailer<<>>\n%%EOF\n"
)


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
        blob_adapter="memory",
        blob_root=tmp_path / "blobs",
        queue_adapter="memory",
    )


def csrf_headers(client: TestClient) -> dict[str, str]:
    csrf = client.cookies.get("hub_csrf") or ""
    return {"X-CSRF": csrf, "Content-Type": "application/json"}


def bootstrap_admin(client: TestClient) -> None:
    token = client.app.state.bootstrap_token
    res = client.post(
        "/api/auth/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "owner@example.test", "password": "correct-horse"},
    )
    assert res.status_code == 200, res.text


def onboard_operator(client: TestClient) -> None:
    saved = client.put("/api/candidate", headers=csrf_headers(client), json=ONBOARDED_CANDIDATE)
    assert saved.status_code == 200, saved.text
    assert saved.json()["onboarded"] is True
    csrf = client.cookies.get("hub_csrf") or ""
    resume = client.put(
        "/api/candidate/resume",
        headers={"X-CSRF": csrf, "Content-Type": "application/pdf"},
        content=MINIMAL_PDF,
    )
    assert resume.status_code == 200, resume.text


def strip_compat_disk(settings: Settings) -> None:
    """Operator-tenant blobs must be enough. Do not let leftover disk files mask the bug."""
    for path in (hub_candidate_path(settings), hub_resume_path(settings)):
        if path.is_file():
            path.unlink()


@pytest.mark.no_candidate
def test_cookieless_agent_join_when_health_and_invite_say_onboarded(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    operator = TestClient(app)
    bootstrap_admin(operator)
    onboard_operator(operator)
    strip_compat_disk(settings)

    created = operator.post(
        "/api/invites",
        headers=csrf_headers(operator),
        json={"track": "discovery", "mode": "agents_only", "max_redemptions": 4},
    )
    assert created.status_code == 200, created.text
    invite_id = created.json()["invite"]["id"]
    secret = created.json()["secret"]

    agent = TestClient(app)
    assert agent.cookies.get("hub_session") in {None, ""}

    health = agent.get("/health")
    assert health.status_code == 200, health.text
    body = health.json()
    assert body["candidate_onboarded"] is True
    assert body["resume_present"] is True
    assert body["ready_for_agents"] is True
    assert body["next_step"] == "ready"

    preview = agent.get(f"/api/join/{invite_id}", params={"s": secret})
    assert preview.status_code == 200, preview.text
    info = preview.json()
    assert info["candidate"]["present"] is True
    assert info["candidate"]["onboarded"] is True
    assert info["join_blocked"] is False
    assert info["join"]["url"] == "/api/auth/join"
    assert info["mode"] == "agents_only"

    joined = agent.post(
        "/api/auth/join",
        json={
            "invite_id": invite_id,
            "s": secret,
            "display_name": "Iron Man",
            "metadata": {
                "model": "grok-4",
                "harness": "cursor-cloud",
                "bed": "cursor",
            },
        },
    )
    assert joined.status_code == 200, joined.text
    payload = joined.json()
    assert payload["kind"] == "agent"
    assert payload["track"] == "discovery"
    assert payload["api_key"].startswith("jh_agt_")
    assert payload["user"]["display_name"] == "Iron Man"

    jobs = agent.get("/api/jobs", headers={"Authorization": f"Bearer {payload['api_key']}"})
    assert jobs.status_code == 200, jobs.text
    assert "jobs" in jobs.json()


@pytest.mark.no_candidate
def test_cookieless_join_stays_blocked_when_candidate_missing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    operator = TestClient(app)
    bootstrap_admin(operator)
    db = operator.app.state.db
    tenant = db.operator_tenant()
    assert tenant is not None
    row, secret = create_invite(
        db,
        track="discovery",
        mode="agents_only",
        max_redemptions=2,
        ttl_hours=72,
        allow_multiple_owners=False,
        created_by="pytest",
        account_id=tenant.account_id,
    )

    agent = TestClient(app)
    health = agent.get("/health").json()
    assert health["candidate_onboarded"] is False
    assert health["next_step"] in {"onboarding", "signup"}

    preview = agent.get(f"/api/join/{row['id']}", params={"s": secret})
    assert preview.status_code == 200, preview.text
    info = preview.json()
    assert info["candidate"]["onboarded"] is False
    assert info["join_blocked"] is True

    joined = agent.post(
        "/api/auth/join",
        json={
            "invite_id": row["id"],
            "s": secret,
            "display_name": "IronMan",
        },
    )
    assert joined.status_code == 409, joined.text
    detail = joined.json()["detail"]
    assert detail["code"] == "candidate_required"
    assert detail["onboarding_url"] == "/onboarding"
    assert "api_key" not in joined.json()
