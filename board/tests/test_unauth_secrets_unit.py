"""Unit tests: auth guards and secret/key leakage on public surfaces.

Unauthenticated responses, static HTML/JS, OpenAPI, health, and error payloads
must never contain live API keys, role tokens, bootstrap secrets, or NEXT_PUBLIC
secret values. Auth authenticate() must reject missing credentials.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.auth import authenticate
from app.db import BoardDB
from app.main import STATIC_DIR, create_app
from tests.unauth_support import (
    CANDIDATE_EMAIL,
    CANDIDATE_NAME,
    JOB_COMPANY,
    SENSITIVE_SUBSTRINGS,
    TOKENS,
    SeededHub,
    assert_unauthenticated_denied,
    hub_settings,
    make_seeded_hub,
    secret_like_patterns,
    write_canary_candidate,
)

STATIC_SECRET_RE = re.compile("|".join(secret_like_patterns()))

# HTML/API paths that must not be callable without a principal / onboarding guard.
PROTECTED_ROUTE_PATHS = frozenset(
    {
        "/",
        "/admin",
        "/admin/invites",
        "/admin/data",
        "/admin/users",
        "/onboarding",
        "/api/jobs",
        "/api/jobs/{job_id}",
        "/api/people",
        "/api/people/{person_id}",
        "/api/candidate",
        "/api/candidate/public",
        "/api/candidate/resume",
        "/api/candidate/status",
        "/api/candidate/template",
        "/api/events",
        "/api/hygiene",
        "/api/metrics/summary",
        "/api/metrics/token_burn",
        "/api/export/ledger",
        "/api/messages",
        "/api/queue",
        "/api/queue/mine",
        "/api/presence",
        "/api/presence/{user_id}",
        "/api/users",
        "/api/agents",
        "/api/invites",
        "/api/meta",
        "/api/whoami",
        "/api/auth/me",
        "/api/onboarding",
        "/api/a2a/directory",
        "/api/a2a/peers",
        "/api/registry/skills",
        "/api/registry/skills/{skill_id}",
        "/api/registry/mcps",
        "/api/registry/mcps/{mcp_id}",
        "/api/registry/recordings",
        "/api/registry/recordings/{recording_id}",
        "/admin/skills",
        "/api/memory/recall",
        "/api/memory/items",
        "/api/memory/items/{item_id}",
        "/api/memory/items/{item_id}/move",
        "/api/memory/items/{item_id}/solidify",
        "/api/memory/pods",
        "/admin/memory",
    }
)


@pytest.fixture()
def seeded(tmp_path: Path) -> SeededHub:
    return make_seeded_hub(tmp_path)


def test_authenticate_without_credentials_is_401(tmp_path: Path) -> None:
    write_canary_candidate(tmp_path)
    settings = hub_settings(tmp_path)
    db = BoardDB(settings.db_path)
    with pytest.raises(HTTPException) as exc:
        authenticate(settings, db)
    assert exc.value.status_code == 401
    detail = str(exc.value.detail)
    for token in TOKENS.values():
        assert token not in detail


def test_authenticate_wrong_role_token_is_401_and_does_not_echo_secret(
    tmp_path: Path,
) -> None:
    write_canary_candidate(tmp_path)
    settings = hub_settings(tmp_path)
    db = BoardDB(settings.db_path)
    with pytest.raises(HTTPException) as exc:
        authenticate(
            settings,
            db,
            x_role="admin",
            x_token="wrong-token-not-the-canary",
        )
    assert exc.value.status_code == 401
    assert TOKENS["admin"] not in str(exc.value.detail)


def test_static_html_js_does_not_embed_live_secrets() -> None:
    assert STATIC_DIR.is_dir(), "board static dir missing"
    offenders: list[str] = []
    for path in STATIC_DIR.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".html", ".js", ".css", ".json", ".txt", ".map"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if STATIC_SECRET_RE.search(text):
            offenders.append(str(path.relative_to(STATIC_DIR)))
        for token in TOKENS.values():
            if token in text:
                offenders.append(f"{path.name} contains test role token")
    assert not offenders, f"static assets embed secret-like values: {offenders}"


def test_repo_public_frontend_has_no_next_public_secret_assignments() -> None:
    root = Path(__file__).resolve().parents[2]
    pattern = re.compile(r"NEXT_PUBLIC_[A-Z0-9_]+\s*=\s*['\"](?!\$\{)[^'\"]+['\"]")
    hits: list[str] = []
    for folder in (root / "board" / "app" / "static", root / "board" / "app"):
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".html", ".js", ".ts", ".tsx", ".env", ".json"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if pattern.search(text):
                hits.append(str(path))
    assert not hits, f"NEXT_PUBLIC secret assignments in public frontend: {hits}"


def test_unauthenticated_health_and_agent_card_do_not_leak_secrets_or_pii(
    seeded: SeededHub,
) -> None:
    for path in (
        "/health",
        "/ready",
        "/.well-known/agent-card.json",
        "/.well-known/agent.json",
        "/a2a",
        "/a2a/agent-card.json",
        "/login",
        "/api/registry/catalog",
        "/llms.txt",
        "/agents.txt",
        "/.well-known/llms.txt",
        "/.well-known/agents.txt",
        "/brand/mascot.png",
        "/brand/logo.png",
    ):
        res = seeded.unauth.get(path)
        body = res.text or ""
        header_blob = " ".join(f"{k}: {v}" for k, v in res.headers.items())
        blob = body + "\n" + header_blob
        leaked = [item for item in SENSITIVE_SUBSTRINGS if item in blob]
        assert not leaked, (
            f"unauthenticated {path} leaked {leaked!r} (status {res.status_code})"
        )
        assert CANDIDATE_EMAIL not in blob
        assert CANDIDATE_NAME not in blob
        assert JOB_COMPANY not in blob
        for token in TOKENS.values():
            assert token not in blob
        assert "jh_boot_" not in blob


def test_unauthenticated_error_payloads_do_not_include_tokens_or_pii(
    seeded: SeededHub,
) -> None:
    res = seeded.unauth.get("/api/jobs")
    body = res.text or ""
    for token in TOKENS.values():
        assert token not in body
    assert JOB_COMPANY not in body
    assert CANDIDATE_EMAIL not in body
    login = seeded.unauth.post(
        "/api/auth/login",
        json={"email": CANDIDATE_EMAIL, "password": "wrong-password"},
    )
    err = login.text or ""
    assert "password_hash" not in err
    assert TOKENS["admin"] not in err
    assert CANDIDATE_EMAIL not in err
    bootstrap = seeded.unauth.post(
        "/api/auth/bootstrap",
        json={"email": "x@example.test", "password": "x"},
    )
    boot_body = bootstrap.text or ""
    token = getattr(seeded.app.state, "bootstrap_token", "") or ""
    if token:
        assert token not in boot_body
        assert token not in (bootstrap.headers.get("x-bootstrap-token") or "")


def test_unauthenticated_openapi_and_docs_do_not_dump_live_keys(seeded: SeededHub) -> None:
    for path in ("/openapi.json", "/docs", "/redoc"):
        res = seeded.unauth.get(path)
        body = res.text or ""
        for token in TOKENS.values():
            assert token not in body, f"{path} leaked role token"
        assert JOB_COMPANY not in body
        assert CANDIDATE_EMAIL not in body
        # Contract: schema dump is not public.
        assert_unauthenticated_denied(res, what=f"GET {path} (API schema dump)")


def _endpoint_declares_auth(route: APIRoute) -> bool:
    try:
        signature = inspect.signature(route.endpoint)
    except (TypeError, ValueError):
        return False
    for name, param in signature.parameters.items():
        annotation = str(param.annotation)
        if name in {"principal", "access"} or "Principal" in annotation:
            return True
        default = param.default
        if default is not inspect.Parameter.empty and "Depends" in type(default).__name__:
            dep = getattr(default, "dependency", None)
            dep_name = getattr(dep, "__name__", "") if dep is not None else ""
            if dep_name in {
                "dependency",
                "require_onboarding_access",
                "require_principal",
            }:
                return True
    names = []
    dependant = getattr(route, "dependant", None)
    if dependant is not None:
        for dep in getattr(dependant, "dependencies", []) or []:
            call = getattr(dep, "call", None)
            names.append(getattr(call, "__name__", "") if call is not None else "")
    return any(
        name in {"dependency", "require_onboarding_access", "require_principal"}
        for name in names
    )


def test_sensitive_routes_declare_an_auth_guard(tmp_path: Path) -> None:
    write_canary_candidate(tmp_path)
    app = create_app(hub_settings(tmp_path))
    missing: list[str] = []
    seen: set[str] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        if path not in PROTECTED_ROUTE_PATHS:
            continue
        seen.add(path)
        if not _endpoint_declares_auth(route):
            missing.append(f"{','.join(sorted(route.methods))} {path}")
    assert PROTECTED_ROUTE_PATHS <= seen | {"/api/queue"}, (
        f"expected routes not registered: {sorted(PROTECTED_ROUTE_PATHS - seen)}"
    )
    assert not missing, (
        "sensitive routes are callable without a principal/onboarding dependency "
        f"(unauthenticated users can hit them): {missing}"
    )


def test_settings_tokens_never_appear_in_public_json(seeded: SeededHub) -> None:
    client: TestClient = seeded.unauth
    for path in (
        "/health",
        "/ready",
        "/api/meta",
        "/api/jobs",
        "/openapi.json",
        "/.well-known/agent-card.json",
    ):
        res = client.get(path)
        blob = (res.text or "") + " ".join(res.headers.values())
        for role, token in TOKENS.items():
            assert token not in blob, (
                f"unauthenticated {path} leaked {role} token (status {res.status_code})"
            )
