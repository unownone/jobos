"""Admin bootstrap: one-time token, hash in SQLite, wipe plaintext, compat APIs."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import BOOTSTRAP_PREFIX, format_signup_url, sha256_hex
from app.constants import ROLES
from app.db import BoardDB
from app.main import create_app
from app.settings import Settings, parse_env_file

TOKENS = {role: f"test-token-{role}-not-real" for role in ROLES}
ENSURE = Path(__file__).resolve().parents[2] / "scripts" / "hub_ensure_bootstrap.py"
DEPLOY = Path(__file__).resolve().parents[2] / "scripts" / "hub_deploy.sh"


def _settings(tmp_path: Path, *, public_url: str = "") -> Settings:
    return Settings(
        board_dir=tmp_path,
        db_path=tmp_path / "board.db",
        host="0.0.0.0",
        port=8787,
        tokens=dict(TOKENS),
        public_url=public_url,
        bootstrap_token="",
        env_path=tmp_path / ".env",
        tokens_json_path=tmp_path / "tokens.local.json",
    )


def h(role: str, actor: str = "pytest") -> dict[str, str]:
    return {"X-Role": role, "X-Token": TOKENS[role], "X-Actor": actor}


@pytest.fixture()
def hub(tmp_path: Path) -> tuple[TestClient, Settings]:
    settings = _settings(tmp_path, public_url="https://hub.example.test")
    return TestClient(create_app(settings)), settings


def test_fresh_start_mints_bootstrap_and_health_false(hub: tuple[TestClient, Settings]) -> None:
    client, settings = hub
    token = client.app.state.bootstrap_token
    assert token.startswith(BOOTSTRAP_PREFIX)
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["ok"] is True
    assert body["admin_bootstrapped"] is False
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    assert ready.json()["admin_bootstrapped"] is False
    env = parse_env_file(settings.env_path)
    assert env["HUB_BOOTSTRAP_TOKEN"] == token
    local = json.loads(settings.tokens_json_path.read_text(encoding="utf-8"))
    assert local["bootstrap"] == token
    meta = BoardDB(settings.db_path).get_secret_meta("bootstrap")
    assert meta is not None
    assert meta["used_at"] is None
    assert meta["value_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in meta["value_hash"]
    assert sha256_hex(token) == meta["value_hash"]


def test_signup_url_uses_hub_public_url(hub: tuple[TestClient, Settings]) -> None:
    client, settings = hub
    token = client.app.state.bootstrap_token
    url = format_signup_url(settings, token)
    assert url == f"https://hub.example.test/admin/signup#bootstrap={token}"
    page = client.get("/admin/signup")
    assert page.status_code == 200
    assert "Job Hub — Admin" in page.text


def test_bootstrap_creates_admin_once_and_wipes_plaintext(
    hub: tuple[TestClient, Settings],
) -> None:
    client, settings = hub
    token = client.app.state.bootstrap_token
    first = client.post(
        "/api/auth/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "owner@example.test", "password": "correct-horse"},
    )
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["ok"] is True
    assert payload["admin_bootstrapped"] is True
    assert payload["user"]["kind"] == "admin"
    assert payload["user"]["email"] == "owner@example.test"
    assert "hub_session" in first.cookies
    assert client.get("/health").json()["admin_bootstrapped"] is True

    env = parse_env_file(settings.env_path)
    assert not env.get("HUB_BOOTSTRAP_TOKEN")
    assert env.get("HUB_BOOTSTRAP_USED") == "1"
    local = json.loads(settings.tokens_json_path.read_text(encoding="utf-8"))
    assert "bootstrap" not in local
    meta = BoardDB(settings.db_path).get_secret_meta("bootstrap")
    assert meta is not None
    assert meta["used_at"]
    assert meta["value_hash"] == sha256_hex(token)

    second = client.post(
        "/api/auth/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "other@example.test", "password": "correct-horse"},
    )
    assert second.status_code == 403

    listed = client.get("/api/jobs", headers=h("discovery"))
    assert listed.status_code == 200
    assert listed.json()["count"] == 0


def test_existing_job_apis_still_work_after_bootstrap(
    hub: tuple[TestClient, Settings],
) -> None:
    client, settings = hub
    created = client.post(
        "/api/jobs",
        headers=h("discovery"),
        json={
            "id": "remoteok__hub1",
            "company": "Acme",
            "title": "Staff Engineer",
            "apply_url": "https://jobs.example.com/staff-hub",
            "sources": ["remoteok"],
            "status": "apply_ready",
            "apply_packet": {"url": "https://jobs.example.com/staff-hub", "steps": ["Open"]},
        },
    )
    assert created.status_code == 201, created.text
    token = client.app.state.bootstrap_token
    boot = client.post(
        "/api/auth/bootstrap",
        json={"email": "owner@example.test", "password": "correct-horse", "token": token},
    )
    assert boot.status_code == 200, boot.text
    listed = client.get("/api/jobs", headers=h("apply"))
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["jobs"][0]["id"] == "remoteok__hub1"


def test_hub_ensure_bootstrap_prints_signup_url(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["HUB_PUBLIC_URL"] = "http://hub.internal:8787"
    env.pop("HUB_BOOTSTRAP_TOKEN", None)
    result = subprocess.run(
        [sys.executable, str(ENSURE), "--dir", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "Admin signup: http://hub.internal:8787/admin/signup#bootstrap=jh_boot_" in result.stdout
    assert str(tmp_path / ".env") in result.stdout
    assert "Do not commit" in result.stdout
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "HUB_BOOTSTRAP_TOKEN=jh_boot_" in env_text


def test_hub_deploy_dry_run_prints_paths(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(DEPLOY)],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HUB_DEPLOY_DRY_RUN": "1",
            "HUB_PUBLIC_URL": "http://127.0.0.1:8787",
            "JOBHUB_BOARD_DIR": str(tmp_path),
        },
    )
    combined = result.stdout + result.stderr
    assert "gitignored secrets" in combined.lower() or "Gitignored secrets" in combined
    assert "8787" in combined
    assert "HUB_DEPLOY_DRY_RUN=1" in combined
    assert "Admin signup:" in combined
    assert "jh_boot_" in combined
