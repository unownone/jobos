"""Phase E: /api/onboarding, pack zip, allowlisted raw files. No secrets."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.constants import ROLES
from app.main import create_app
from app.pack import public_candidate
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


def make_invite(client: TestClient, track: str) -> tuple[str, str]:
    bootstrap_admin(client)
    created = client.post(
        "/api/invites",
        headers=csrf_headers(client),
        json={"track": track, "max_redemptions": 8, "ttl_hours": 72, "mode": "owner_then_agents"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    return body["invite"]["id"], body["secret"]


def test_onboarding_unauthenticated_without_invite_401(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    res = client.get("/api/onboarding")
    assert res.status_code == 401


def test_discovery_invite_onboarding_skills_and_no_apply_secrets(
    hub: tuple[TestClient, Settings],
) -> None:
    client, _settings = hub
    invite_id, secret = make_invite(client, "discovery")
    q = {"invite_id": invite_id, "s": secret}
    res = client.get("/api/onboarding", params=q)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["track"] == "discovery"
    assert body["candidate"]["present"] is True
    names = [row["name"] for row in body["skills"]]
    assert "job-discovery" in names
    assert "skill-and-mcp-catalog" in names
    assert "deep-research" in names
    assert "job-apply" not in names
    urls = [u for row in body["skills"] for u in row["files"]]
    assert "/api/skills/job-discovery/SKILL.md" in urls
    assert body["process"]["catalog_first"] is True
    assert "Easy Apply" in body["process"]["forbidden"]
    connector_ids = [c["id"] for c in body["connectors_needed"]]
    assert connector_ids == [
        "gmail",
        "google_drive",
        "google_calendar",
        "indeed",
        "exa",
    ]
    blob = json.dumps(body)
    assert "sk-" not in blob
    assert "API_KEY=" not in blob
    assert "correct-horse" not in blob
    for item in body["connectors_needed"]:
        assert "secret" not in item
        assert item["env_fallback"]
        assert "value" not in item
    apply_skill = client.get("/api/skills/job-apply/SKILL.md", params=q)
    assert apply_skill.status_code == 404
    discovery_skill = client.get("/api/skills/job-discovery/SKILL.md", params=q)
    assert discovery_skill.status_code == 200
    assert "job-discovery" in discovery_skill.text.lower() or "Discovery" in discovery_skill.text
    join = client.get(f"/api/join/{invite_id}", params={"s": secret})
    assert join.status_code == 200
    info = join.json()
    assert info["onboarding"]["available"] is True
    assert info["onboarding"]["url"] == "/api/onboarding"
    assert info["hub"]["pack_sha"]
    assert info["candidate"]["present"] is True


def test_application_zip_contains_job_apply(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    invite_id, secret = make_invite(client, "application")
    q = {"invite_id": invite_id, "s": secret}
    res = client.get("/api/packs/current/skills.zip", params=q)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        names = zf.namelist()
        assert "skills/job-apply/SKILL.md" in names
        assert "INSTALL.md" in names
        assert "skills/deep-research/SKILL.md" in names
        assert not any(n.endswith(".env") for n in names)
        assert "profiles/candidate.yaml" not in names
        skill = zf.read("skills/job-apply/SKILL.md").decode("utf-8")
        assert "job-apply" in skill.lower() or "Apply" in skill


def test_docs_path_traversal_is_404(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    invite_id, secret = make_invite(client, "discovery")
    q = {"invite_id": invite_id, "s": secret}
    for path in (
        "/api/docs/../board/.env",
        "/api/docs/%2e%2e/board/.env",
        "/api/docs/board/.env",
        "/api/docs/profiles/candidate.yaml",
        "/api/skills/job-discovery/../../../board/.env",
        "/api/scripts/../hub_deploy.sh",
        "/api/mcp/hosted/../mcp.example.json",
    ):
        res = client.get(path, params=q)
        assert res.status_code == 404, path
    ok = client.get("/api/docs/docs/process.md", params=q)
    assert ok.status_code == 200
    assert "Easy Apply" in ok.text
    mcp = client.get("/api/mcp/example.json", params=q)
    assert mcp.status_code == 200
    example = mcp.json()
    dumped = json.dumps(example)
    assert "${" in dumped or "FIRECRAWL_API_KEY" in dumped
    assert "sk-live" not in dumped
    script = client.get("/api/scripts/install_agent_skills.sh", params=q)
    assert script.status_code == 200
    assert "npx" in script.text
    forbidden_script = client.get("/api/scripts/hub_deploy.sh", params=q)
    assert forbidden_script.status_code == 404


def test_candidate_present_false_in_this_workspace(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    assert not Path("/workspace/profiles/candidate.yaml").is_file()
    invite_id, secret = make_invite(client, "outreach")
    body = client.get("/api/onboarding", params={"invite_id": invite_id, "s": secret}).json()
    assert body["candidate"]["present"] is True
    assert "target.titles" in body["candidate"]["fields_public"]
    assert "phone" not in json.dumps(body["candidate"])
    gmail = next(c for c in body["connectors_needed"] if c["id"] == "gmail")
    assert gmail["required"] is True


def test_compat_role_and_rebuild(hub: tuple[TestClient, Settings]) -> None:
    client, _settings = hub
    denied = client.post("/api/packs/rebuild", headers={"X-Role": "discovery", "X-Token": TOKENS["discovery"]})
    assert denied.status_code == 403
    onboard = client.get(
        "/api/onboarding",
        headers={"X-Role": "apply", "X-Token": TOKENS["apply"]},
    )
    assert onboard.status_code == 200
    assert onboard.json()["track"] == "application"
    names = [row["name"] for row in onboard.json()["skills"]]
    assert "job-apply" in names
    rebuilt = client.post(
        "/api/packs/rebuild",
        headers={"X-Role": "admin", "X-Token": TOKENS["admin"], "X-Actor": "maintainer"},
    )
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()["pack_sha"]
    assert rebuilt.json()["files"] > 0
    maint = client.get(
        "/api/onboarding",
        headers={"X-Role": "maintenance", "X-Token": TOKENS["maintenance"]},
    )
    assert maint.status_code == 200
    assert any(s["name"] == "skill-maintainer" for s in maint.json()["skills"])
    assert maint.json()["catalog_updated_at"] == "2026-09-15"


@pytest.mark.no_candidate
def test_public_candidate_omits_phone(tmp_path: Path) -> None:
    (tmp_path / "profiles").mkdir(exist_ok=True)
    (tmp_path / "profiles" / "candidate.yaml").write_text(
        "identity:\n"
        '  full_name: "Secret Person"\n'
        '  phone: "555-0100"\n'
        '  email: "hidden@example.test"\n'
        '  work_authorization: "US citizen"\n'
        "target:\n"
        "  titles:\n"
        '    - "Staff Engineer"\n'
        "  locations:\n"
        '    - "Remote"\n'
        "  deal_breakers:\n"
        '    - "Crypto"\n',
        encoding="utf-8",
    )
    slice_ = public_candidate(tmp_path)
    assert slice_["present"] is True
    dumped = json.dumps(slice_)
    assert "555-0100" not in dumped
    assert "hidden@example.test" not in dumped
    assert "Secret Person" not in dumped
    assert slice_["target"]["titles"] == ["Staff Engineer"]
    assert slice_["work_authorization"] == "US citizen"
