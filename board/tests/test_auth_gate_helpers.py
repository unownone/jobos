"""Unit tests for auth-gate helpers (not the withheld unauthenticated e2e suite)."""

from __future__ import annotations

from app.auth_gate import path_is_public, redact_secrets, safe_next_path


def test_path_is_public_allowlist() -> None:
    assert path_is_public("/") is True
    assert path_is_public("/start") is True
    assert path_is_public("/static/public.css") is True
    assert path_is_public("/health") is True
    assert path_is_public("/ready") is True
    assert path_is_public("/login") is True
    assert path_is_public("/admin/signup") is True
    assert path_is_public("/api/auth/signup") is True
    assert path_is_public("/api/auth/join") is True
    assert path_is_public("/join/inv_123") is True
    assert path_is_public("/api/join/inv_123") is True
    assert path_is_public("/.well-known/agent-card.json") is True
    assert path_is_public("/a2a") is True
    assert path_is_public("/a2a/application/agent-card.json") is True
    assert path_is_public("/api/registry/catalog") is True
    assert path_is_public("/llms.txt") is True
    assert path_is_public("/agents.txt") is True
    assert path_is_public("/.well-known/llms.txt") is True
    assert path_is_public("/.well-known/agents.txt") is True
    assert path_is_public("/brand/mascot.png") is True
    assert path_is_public("/brand/logo.png") is True
    assert path_is_public("/static/hub.css") is True
    assert path_is_public("/static/hub.js") is True


def test_path_is_public_rejects_sensitive_surfaces() -> None:
    for path in (
        "/board",
        "/onboarding",
        "/admin",
        "/admin/invites",
        "/admin/data",
        "/admin/users",
        "/admin/skills",
        "/admin/memory",
        "/static/index.html",
        "/static/admin.html",
        "/api/jobs",
        "/api/jobs/remoteok__1",
        "/api/candidate",
        "/api/candidate/public",
        "/api/candidate/status",
        "/api/candidate/resume",
        "/api/people",
        "/api/events",
        "/api/onboarding",
        "/api/a2a/directory",
        "/api/presence",
        "/api/users",
        "/api/meta",
        "/api/registry/skills",
        "/api/registry/mcps",
        "/api/memory/recall",
        "/docs",
        "/openapi.json",
    ):
        assert path_is_public(path) is False, path


def test_safe_next_path_blocks_open_redirects() -> None:
    assert safe_next_path("/admin") == "/admin"
    assert safe_next_path("/onboarding") == "/onboarding"
    assert safe_next_path("https://evil.example/phish") == "/"
    assert safe_next_path("//evil.example") == "/"
    assert safe_next_path("/login") == "/"
    assert safe_next_path("/admin/signup") == "/"


def test_redact_secrets_drops_keys_and_hub_prefixes() -> None:
    payload = {
        "message": "ok",
        "api_key": "jh_agt_should-not-leak",
        "nested": {"password": "secret", "role": "admin"},
    }
    cleaned = redact_secrets(payload)
    assert cleaned["message"] == "ok"
    assert "api_key" not in cleaned
    assert cleaned["nested"]["role"] == "admin"
    assert "password" not in cleaned["nested"]
    assert redact_secrets("bearer jh_own_discovery_abc") == "authentication required"
