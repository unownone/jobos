"""AuthManager: one resolution per request. No Postgres and no Cloudflare network."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import socket
import subprocess
import time
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.auth import authenticate, optional_principal, require_principal
from app.auth_gate import AuthGateMiddleware
from app.auth_manager import AuthConflict, AuthManager, install_secret_log_filter
from app.bootstrap import sha256_hex
from app.gates import CandidateGateMiddleware
from app.presence import wrap_principal_with_activity
from app.settings import Settings, load_settings
from app.tenant import COMPAT_ACCOUNT_ID

ISSUER = "https://contoso.cloudflareaccess.com"
AUDIENCE = "aud-test-123"
STAMP = "2020-01-01T00:00:00Z"


@pytest.fixture(scope="session", autouse=True)
def postgres_server():
    """These tests use an in-memory directory, not the Hub database."""
    yield ""


def make_settings(tmp_path: Path | None = None, **overrides: object) -> Settings:
    root = tmp_path or Path("/tmp/auth-manager-unit")
    values: dict[str, object] = {
        "board_dir": root,
        "db_path": root / "board.db",
        "host": "127.0.0.1",
        "port": 8787,
        "tokens": {
            "discovery": "token-discovery",
            "apply": "token-apply",
            "outreach": "token-outreach",
            "admin": "token-admin",
            "maintenance": "token-maintenance",
        },
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def make_request(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> Request:
    raw: list[tuple[bytes, bytes]] = []
    for name, value in (headers or {}).items():
        raw.append((name.lower().encode("latin-1"), value.encode("latin-1")))
    if cookies:
        cookie = "; ".join(f"{key}={value}" for key, value in cookies.items())
        raw.append((b"cookie", cookie.encode("latin-1")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": raw,
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
    }
    return Request(scope)


class MemoryDirectory:
    def __init__(self) -> None:
        self.users: dict[str, dict] = {}
        self.keys: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.lookups: list[str] = []
        self.deleted_sessions: list[str] = []
        self.touches: list[tuple[str, str]] = []

    def add_user(self, user: dict) -> dict:
        self.users[user["id"]] = user
        return user

    def add_key(
        self,
        secret: str,
        user: dict,
        *,
        account_id: str = "acc_from_key_row",
        revoked_at: str | None = None,
    ) -> None:
        self.keys[sha256_hex(secret)] = {
            "id": f"key_{user['id']}",
            "user_id": user["id"],
            "account_id": account_id,
            "revoked_at": revoked_at,
            "prefix": secret[:10],
            "key_hash": sha256_hex(secret),
        }

    def add_session(
        self,
        token: str,
        user: dict,
        *,
        csrf: str,
        expires_at: str = "2999-01-01T00:00:00Z",
    ) -> None:
        self.sessions[sha256_hex(token)] = {
            "id": f"sess_{user['id']}",
            "user_id": user["id"],
            "account_id": user["account_id"],
            "token_hash": sha256_hex(token),
            "expires_at": expires_at,
            "last_seen": STAMP,
            "csrf_hash": sha256_hex(csrf),
        }

    def get_api_key_by_hash(self, key_hash: str) -> dict | None:
        self.lookups.append(key_hash)
        return self.keys.get(key_hash)

    def get_user(self, user_id: str) -> dict | None:
        return self.users.get(user_id)

    def get_user_by_email(self, email: str) -> dict | None:
        want = email.strip().lower()
        for user in self.users.values():
            if (user.get("email") or "").lower() == want:
                return user
        return None

    def get_session_by_token_hash(self, token_hash: str) -> dict | None:
        return self.sessions.get(token_hash)

    def delete_session(self, session_id: str) -> None:
        self.deleted_sessions.append(session_id)
        self.sessions = {key: row for key, row in self.sessions.items() if row["id"] != session_id}

    def touch_session(self, session_id: str, expires_at: str) -> None:
        self.touches.append((session_id, expires_at))


def agent_user(
    *,
    user_id: str = "usr_ada",
    account_id: str = "acc_user",
    email: str = "ada@example.test",
    kind: str = "agent",
) -> dict:
    return {
        "id": user_id,
        "account_id": account_id,
        "kind": kind,
        "track": "discovery",
        "email": email,
        "display_name": "Ada",
        "disabled_at": None,
        "password_hash": None,
        "metadata": {},
        "created_by": None,
        "created_at": STAMP,
    }


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def rsa_pems(tmp_path: Path, name: str = "access") -> tuple[Path, str]:
    private = tmp_path / f"{name}-private.pem"
    public = tmp_path / f"{name}-public.pem"
    subprocess.run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:2048",
            "-out",
            str(private),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
        check=True,
        capture_output=True,
    )
    return private, public.read_text(encoding="ascii")


def access_token(
    private_key: Path,
    *,
    email: str = "Ada@Example.Test",
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    exp: int | None = None,
    extra: dict | None = None,
) -> str:
    payload: dict = {
        "email": email,
        "iss": issuer,
        "aud": audience,
        "exp": int(time.time()) + 600 if exp is None else exp,
    }
    if extra:
        payload.update(extra)
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing = f"{header}.{body}".encode("ascii")
    signed = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", str(private_key)],
        input=signing,
        check=True,
        capture_output=True,
    )
    return signing.decode("ascii") + "." + _b64url(signed.stdout)


def hs256_token(secret: str, claims: dict) -> str:
    header = _b64url(json.dumps({"alg": "HS256"}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing = f"{header}.{body}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing, hashlib.sha256).digest()
    return signing.decode("ascii") + "." + _b64url(signature)


def test_default_auth_methods_are_hub_key_then_session(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    assert settings.auth_methods == "hub_key,session"
    manager = AuthManager.from_settings(settings, MemoryDirectory())
    assert [method.name for method in manager.methods] == ["hub_key", "session"]


def test_load_settings_reads_auth_and_access_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_METHODS", " session, hub_key ")
    monkeypatch.setenv("ACCESS_TEAM_DOMAIN", "contoso.cloudflareaccess.com")
    monkeypatch.setenv("ACCESS_AUD", AUDIENCE)
    monkeypatch.setenv("ACCESS_JWT_PUBLIC_KEY", "PEM")
    loaded = load_settings()
    assert loaded.auth_methods == "session, hub_key"
    assert loaded.access_team_domain == "contoso.cloudflareaccess.com"
    assert loaded.access_aud == AUDIENCE
    assert loaded.access_jwt_public_key == "PEM"


def test_unknown_auth_method_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, auth_methods="hub_key,nope")
    with pytest.raises(ValueError):
        AuthManager.from_settings(settings, MemoryDirectory())


def test_hub_key_account_comes_only_from_the_user_row(tmp_path: Path) -> None:
    store = MemoryDirectory()
    user = store.add_user(agent_user())
    secret = "jh_agt_account_boundary_secret"
    store.add_key(secret, user, account_id="acc_from_key_row")
    manager = AuthManager.from_settings(make_settings(tmp_path), store)
    request = make_request(
        "GET",
        "/api/jobs",
        headers={
            "Authorization": f"Bearer {secret}",
            "X-Account-Id": "acc_from_header",
        },
    )
    principal = manager.resolve(request)
    assert principal is not None
    assert principal.user_id == "usr_ada"
    assert principal.account_id == "acc_user"
    assert principal.auth == "agent_key"
    assert principal.tenant.account_id == "acc_user"
    assert store.lookups == [sha256_hex(secret)]
    assert secret not in str(principal)


def test_x_hub_key_authenticates(tmp_path: Path) -> None:
    store = MemoryDirectory()
    user = store.add_user(agent_user())
    secret = "jh_agt_header_secret"
    store.add_key(secret, user)
    manager = AuthManager.from_settings(make_settings(tmp_path), store)
    principal = manager.resolve(
        make_request("GET", "/api/jobs", headers={"X-Hub-Key": secret})
    )
    assert principal is not None
    assert principal.user_id == user["id"]


def test_revoked_unknown_and_special_keys_fail_without_echoing_secrets(tmp_path: Path) -> None:
    store = MemoryDirectory()
    user = store.add_user(agent_user())
    revoked = "jh_agt_revoked_secret"
    store.add_key(revoked, user, revoked_at=STAMP)
    manager = AuthManager.from_settings(make_settings(tmp_path), store)
    for secret in (revoked, "jh_agt_unknown_secret", "jh_boot_not_an_api_key", "jh_inv_not_an_api_key"):
        with pytest.raises(HTTPException) as exc:
            manager.resolve(
                make_request("GET", "/api/jobs", headers={"Authorization": f"Bearer {secret}"})
            )
        assert exc.value.status_code == 401
        assert secret not in str(exc.value.detail)


def test_disabled_user_key_is_rejected(tmp_path: Path) -> None:
    store = MemoryDirectory()
    user = store.add_user(agent_user())
    user["disabled_at"] = STAMP
    secret = "jh_agt_disabled_user"
    store.add_key(secret, user)
    manager = AuthManager.from_settings(make_settings(tmp_path), store)
    with pytest.raises(HTTPException) as exc:
        manager.resolve(make_request("GET", "/api/jobs", headers={"Authorization": f"Bearer {secret}"}))
    assert exc.value.status_code == 401
    assert secret not in str(exc.value.detail)


def test_session_csrf_rules_and_touch(tmp_path: Path) -> None:
    store = MemoryDirectory()
    user = store.add_user(agent_user())
    token = "session-token-value"
    csrf = "csrf-value"
    store.add_session(token, user, csrf=csrf)
    manager = AuthManager.from_settings(make_settings(tmp_path), store)
    got = manager.resolve(
        make_request("GET", "/api/jobs", cookies={"hub_session": token, "hub_csrf": csrf})
    )
    assert got is not None
    assert got.auth == "session"
    assert got.csrf_ok is True
    assert got.account_id == "acc_user"
    assert store.touches

    missing = manager.resolve(
        make_request("POST", "/api/jobs", cookies={"hub_session": token, "hub_csrf": csrf})
    )
    assert missing is not None
    assert missing.csrf_ok is False

    ok = manager.resolve(
        make_request(
            "POST",
            "/api/jobs",
            headers={"X-CSRF": csrf},
            cookies={"hub_session": token, "hub_csrf": csrf},
        )
    )
    assert ok is not None
    assert ok.csrf_ok is True


def test_expired_session_is_deleted(tmp_path: Path) -> None:
    store = MemoryDirectory()
    user = store.add_user(agent_user())
    token = "expired-session"
    store.add_session(token, user, csrf="csrf", expires_at="2000-01-01T00:00:00Z")
    manager = AuthManager.from_settings(make_settings(tmp_path), store)
    with pytest.raises(HTTPException) as exc:
        manager.resolve(make_request("GET", "/api/jobs", cookies={"hub_session": token}))
    assert exc.value.status_code == 401
    assert store.deleted_sessions == [f"sess_{user['id']}"]
    assert "expired-session" not in str(exc.value.detail)


def test_first_method_wins_when_both_resolve_the_same_user(tmp_path: Path) -> None:
    store = MemoryDirectory()
    user = store.add_user(agent_user())
    secret = "jh_agt_same_user"
    store.add_key(secret, user)
    store.add_session("sess-token", user, csrf="csrf")
    manager = AuthManager.from_settings(make_settings(tmp_path), store)
    principal = manager.resolve(
        make_request(
            "GET",
            "/api/jobs",
            headers={"Authorization": f"Bearer {secret}"},
            cookies={"hub_session": "sess-token", "hub_csrf": "csrf"},
        )
    )
    assert principal is not None
    assert principal.auth == "agent_key"
    assert principal.user_id == user["id"]


def test_hub_key_wins_over_a_different_session_cookie(tmp_path: Path) -> None:
    store = MemoryDirectory()
    first = store.add_user(agent_user(user_id="usr_a", email="a@example.test"))
    second = store.add_user(agent_user(user_id="usr_b", email="b@example.test", account_id="acc_b"))
    secret = "jh_agt_user_a_secret"
    store.add_key(secret, first)
    store.add_session("sess-b", second, csrf="csrf")
    manager = AuthManager.from_settings(make_settings(tmp_path), store)
    principal = manager.resolve(
        make_request(
            "GET",
            "/api/jobs",
            headers={"Authorization": f"Bearer {secret}"},
            cookies={"hub_session": "sess-b", "hub_csrf": "csrf"},
        )
    )
    assert principal is not None
    assert principal.user_id == "usr_a"
    assert principal.auth == "agent_key"
    assert secret not in str(principal)


def test_access_jwt_before_session_falls_through_on_bad_jwt(tmp_path: Path) -> None:
    private_pem, public_pem = rsa_pems(tmp_path, "jwt-fallthrough")
    store = MemoryDirectory()
    session_user = store.add_user(
        agent_user(user_id="usr_sess", email="sess@example.test", account_id="acc_sess")
    )
    store.add_session("sess-real", session_user, csrf="csrf")
    settings = make_settings(
        tmp_path,
        auth_methods="access_jwt,session",
        access_team_domain="contoso.cloudflareaccess.com",
        access_aud=AUDIENCE,
        access_jwt_public_key=public_pem,
    )
    principal = AuthManager.from_settings(settings, store).resolve(
        make_request(
            "GET",
            "/api/jobs",
            headers={"Cf-Access-Jwt-Assertion": "not.a.jwt"},
            cookies={"hub_session": "sess-real", "hub_csrf": "csrf"},
        )
    )
    assert principal is not None
    assert principal.user_id == "usr_sess"
    assert principal.auth == "session"


def test_access_jwt_before_session_conflicts_for_different_users(tmp_path: Path) -> None:
    private_pem, public_pem = rsa_pems(tmp_path, "jwt-order-conflict")
    store = MemoryDirectory()
    store.add_user(agent_user(user_id="usr_mail", email="ada@example.test", account_id="acc_mail"))
    session_user = store.add_user(
        agent_user(user_id="usr_sess", email="sess@example.test", account_id="acc_sess")
    )
    store.add_session("sess-other", session_user, csrf="csrf")
    token = access_token(private_pem, email="ada@example.test")
    settings = make_settings(
        tmp_path,
        auth_methods="access_jwt,session",
        access_team_domain="contoso.cloudflareaccess.com",
        access_aud=AUDIENCE,
        access_jwt_public_key=public_pem,
    )
    with pytest.raises(AuthConflict) as exc:
        AuthManager.from_settings(settings, store).resolve(
            make_request(
                "GET",
                "/api/jobs",
                headers={"Cf-Access-Jwt-Assertion": token},
                cookies={"hub_session": "sess-other", "hub_csrf": "csrf"},
            )
        )
    assert exc.value.status_code == 401


def test_access_jwt_and_session_for_different_users_conflict(tmp_path: Path) -> None:
    private_pem, public_pem = rsa_pems(tmp_path, "session-conflict")
    store = MemoryDirectory()
    store.add_user(agent_user(user_id="usr_mail", email="ada@example.test", account_id="acc_mail"))
    session_user = store.add_user(
        agent_user(user_id="usr_sess", email="sess@example.test", account_id="acc_sess")
    )
    store.add_session("sess-other", session_user, csrf="csrf")
    token = access_token(private_pem, email="ada@example.test")
    settings = make_settings(
        tmp_path,
        auth_methods="session,access_jwt",
        access_team_domain="contoso.cloudflareaccess.com",
        access_aud=AUDIENCE,
        access_jwt_public_key=public_pem,
    )
    with pytest.raises(AuthConflict) as exc:
        AuthManager.from_settings(settings, store).resolve(
            make_request(
                "GET",
                "/api/jobs",
                headers={"Cf-Access-Jwt-Assertion": token},
                cookies={"hub_session": "sess-other", "hub_csrf": "csrf"},
            )
        )
    assert exc.value.status_code == 401
    detail = str(exc.value.detail)
    assert token not in detail
    assert "usr_mail" not in detail
    assert "usr_sess" not in detail


def test_revoked_key_does_not_fall_through_to_a_valid_session(tmp_path: Path) -> None:
    store = MemoryDirectory()
    user = store.add_user(agent_user())
    secret = "jh_agt_revoked_but_session_ok"
    store.add_key(secret, user, revoked_at=STAMP)
    store.add_session("sess-ok", user, csrf="csrf")
    manager = AuthManager.from_settings(make_settings(tmp_path), store)
    with pytest.raises(HTTPException) as exc:
        manager.resolve(
            make_request(
                "GET",
                "/api/jobs",
                headers={"Authorization": f"Bearer {secret}"},
                cookies={"hub_session": "sess-ok", "hub_csrf": "csrf"},
            )
        )
    assert exc.value.status_code == 401
    assert not isinstance(exc.value, AuthConflict)


def test_client_secret_is_not_a_credential(tmp_path: Path) -> None:
    manager = AuthManager.from_settings(make_settings(tmp_path), MemoryDirectory())
    principal = manager.resolve(
        make_request(
            "GET",
            "/api/jobs",
            headers={"CF-Access-Client-Secret": "shared-account-secret"},
        )
    )
    assert principal is None


def test_access_jwt_is_disabled_unless_team_and_audience_are_set(tmp_path: Path) -> None:
    private_pem, public_pem = rsa_pems(tmp_path, "disabled")
    token = access_token(private_pem)
    store = MemoryDirectory()
    settings = make_settings(
        tmp_path,
        auth_methods="hub_key,session,access_jwt",
        access_jwt_public_key=public_pem,
    )
    manager = AuthManager.from_settings(settings, store)
    assert (
        manager.resolve(
            make_request("GET", "/api/jobs", headers={"Cf-Access-Jwt-Assertion": token})
        )
        is None
    )


def test_access_jwt_maps_email_and_ignores_token_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args, **_kwargs):
        raise AssertionError("access jwt verification touched the network")

    monkeypatch.setattr(socket, "create_connection", explode)
    private_pem, public_pem = rsa_pems(tmp_path, "mapped")
    store = MemoryDirectory()
    user = store.add_user(agent_user(email="ada@example.test", account_id="acc_real"))
    settings = make_settings(
        tmp_path,
        auth_methods="access_jwt",
        access_team_domain="contoso",
        access_aud=AUDIENCE,
        access_jwt_public_key=public_pem,
    )
    token = access_token(
        private_pem,
        email="Ada@Example.Test",
        extra={"account_id": "acc_evil", "role": "admin"},
    )
    principal = AuthManager.from_settings(settings, store).resolve(
        make_request("GET", "/api/jobs", headers={"Cf-Access-Jwt-Assertion": token})
    )
    assert principal is not None
    assert principal.user_id == user["id"]
    assert principal.account_id == "acc_real"
    assert principal.auth == "access_jwt"
    assert token not in str(principal)


def test_access_jwt_rejects_bad_signature_issuer_audience_and_expiry(tmp_path: Path) -> None:
    private_pem, public_pem = rsa_pems(tmp_path, "primary")
    other_pem, _other_public = rsa_pems(tmp_path, "other")
    store = MemoryDirectory()
    store.add_user(agent_user(email="ada@example.test"))
    settings = make_settings(
        tmp_path,
        auth_methods="access_jwt",
        access_team_domain="contoso.cloudflareaccess.com",
        access_aud=AUDIENCE,
        access_jwt_public_key=public_pem,
    )
    manager = AuthManager.from_settings(settings, store)
    cases = [
        access_token(other_pem),
        access_token(private_pem, issuer="https://other.cloudflareaccess.com"),
        access_token(private_pem, audience="other-aud"),
        access_token(private_pem, exp=int(time.time()) - 60),
        hs256_token(
            public_pem,
            {
                "email": "ada@example.test",
                "iss": ISSUER,
                "aud": AUDIENCE,
                "exp": int(time.time()) + 60,
            },
        ),
    ]
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {"email": "ada@example.test", "iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 60}
        ).encode()
    ).rstrip(b"=").decode()
    cases.append(f"{header}.{payload}.")
    for token in cases:
        assert (
            manager.resolve(
                make_request("GET", "/api/jobs", headers={"Cf-Access-Jwt-Assertion": token})
            )
            is None
        )

    assert (
        manager.resolve(
            make_request(
                "GET",
                "/api/jobs",
                headers={
                    "Cf-Access-Jwt-Assertion": access_token(private_pem, email="missing@example.test")
                },
            )
        )
        is None
    )


def test_access_jwt_unknown_email_falls_through_to_session(tmp_path: Path) -> None:
    private_pem, public_pem = rsa_pems(tmp_path, "jwt-unknown-fallthrough")
    store = MemoryDirectory()
    session_user = store.add_user(
        agent_user(user_id="usr_sess", email="sess@example.test", account_id="acc_sess")
    )
    store.add_session("sess-real", session_user, csrf="csrf")
    settings = make_settings(
        tmp_path,
        auth_methods="access_jwt,session",
        access_team_domain="contoso.cloudflareaccess.com",
        access_aud=AUDIENCE,
        access_jwt_public_key=public_pem,
    )
    token = access_token(private_pem, email="missing@example.test")
    principal = AuthManager.from_settings(settings, store).resolve(
        make_request(
            "GET",
            "/api/jobs",
            headers={"Cf-Access-Jwt-Assertion": token},
            cookies={"hub_session": "sess-real", "hub_csrf": "csrf"},
        )
    )
    assert principal is not None
    assert principal.user_id == "usr_sess"
    assert principal.auth == "session"


def test_access_jwt_unknown_email_without_other_credentials_is_401(tmp_path: Path) -> None:
    private_pem, public_pem = rsa_pems(tmp_path, "jwt-unknown-only")
    store = MemoryDirectory()
    store.add_user(agent_user(email="ada@example.test"))
    settings = make_settings(
        tmp_path,
        auth_methods="access_jwt",
        access_team_domain="contoso.cloudflareaccess.com",
        access_aud=AUDIENCE,
        access_jwt_public_key=public_pem,
    )
    token = access_token(private_pem, email="missing@example.test")
    assert (
        AuthManager.from_settings(settings, store).resolve(
            make_request("GET", "/api/jobs", headers={"Cf-Access-Jwt-Assertion": token})
        )
        is None
    )
    with pytest.raises(HTTPException) as exc:
        authenticate(
            settings,
            store,
            request=make_request("GET", "/api/jobs", headers={"Cf-Access-Jwt-Assertion": token}),
        )
    assert exc.value.status_code == 401


def test_access_jwt_and_hub_key_for_different_users_conflict(tmp_path: Path) -> None:
    private_pem, public_pem = rsa_pems(tmp_path, "conflict")
    store = MemoryDirectory()
    key_user = store.add_user(agent_user(user_id="usr_key", email="key@example.test"))
    store.add_user(agent_user(user_id="usr_mail", email="ada@example.test", account_id="acc_mail"))
    secret = "jh_agt_conflict_secret"
    store.add_key(secret, key_user)
    token = access_token(private_pem, email="ada@example.test")
    settings = make_settings(
        tmp_path,
        auth_methods="hub_key,access_jwt",
        access_team_domain="contoso.cloudflareaccess.com",
        access_aud=AUDIENCE,
        access_jwt_public_key=public_pem,
    )
    with pytest.raises(AuthConflict):
        AuthManager.from_settings(settings, store).resolve(
            make_request(
                "GET",
                "/api/jobs",
                headers={
                    "Authorization": f"Bearer {secret}",
                    "Cf-Access-Jwt-Assertion": token,
                },
            )
        )


def test_compat_and_session_in_auth_methods_ignore_none_user_id_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Session normally skips when role tokens are present; patch only for this dual-match case."""
    store = MemoryDirectory()
    user = store.add_user(agent_user(user_id="usr_sess", email="sess@example.test"))
    store.add_session("sess-dual", user, csrf="csrf")
    settings = make_settings(tmp_path, auth_methods="session,compat")
    monkeypatch.setattr("app.auth_manager._presented_role_token", lambda _request: False)
    principal = AuthManager.from_settings(settings, store).resolve(
        make_request(
            "GET",
            "/api/jobs",
            headers={"X-Role": "discovery", "X-Token": "token-discovery", "X-Actor": "pytest"},
            cookies={"hub_session": "sess-dual", "hub_csrf": "csrf"},
        )
    )
    assert principal is not None
    assert principal.user_id == "usr_sess"
    assert principal.auth == "session"


def test_compat_before_session_prefers_session_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MemoryDirectory()
    user = store.add_user(agent_user(user_id="usr_sess", email="sess@example.test"))
    store.add_session("sess-dual", user, csrf="csrf")
    settings = make_settings(tmp_path, auth_methods="compat,session")
    monkeypatch.setattr("app.auth_manager._presented_role_token", lambda _request: False)
    principal = AuthManager.from_settings(settings, store).resolve(
        make_request(
            "GET",
            "/api/jobs",
            headers={"X-Role": "discovery", "X-Token": "token-discovery", "X-Actor": "pytest"},
            cookies={"hub_session": "sess-dual", "hub_csrf": "csrf"},
        )
    )
    assert principal is not None
    assert principal.user_id == "usr_sess"
    assert principal.auth == "session"


def test_compat_tokens_still_authenticate_without_a_hub_key_or_session(tmp_path: Path) -> None:
    manager = AuthManager.from_settings(make_settings(tmp_path), MemoryDirectory())
    principal = manager.resolve(
        make_request(
            "GET",
            "/api/jobs",
            headers={"X-Role": "discovery", "X-Token": "token-discovery", "X-Actor": "pytest"},
        )
    )
    assert principal is not None
    assert principal.auth == "compat_role"
    assert principal.role == "discovery"
    assert principal.actor == "pytest"
    assert principal.account_id == COMPAT_ACCOUNT_ID


def test_role_token_wins_over_a_session_cookie(tmp_path: Path) -> None:
    store = MemoryDirectory()
    admin = store.add_user(
        agent_user(user_id="usr_admin", email="owner@example.test", account_id="acc_admin", kind="admin")
    )
    store.add_session("sess-admin", admin, csrf="csrf")
    manager = AuthManager.from_settings(make_settings(tmp_path), store)
    principal = manager.resolve(
        make_request(
            "GET",
            "/api/jobs",
            headers={"X-Role": "apply", "X-Token": "token-apply"},
            cookies={"hub_session": "sess-admin", "hub_csrf": "csrf"},
        )
    )
    assert principal is not None
    assert principal.auth == "compat_role"
    assert principal.role == "apply"
    assert principal.account_id == COMPAT_ACCOUNT_ID
    assert store.touches == []


def test_authenticate_without_credentials_is_401(tmp_path: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        authenticate(make_settings(tmp_path), MemoryDirectory())
    assert exc.value.status_code == 401


def test_authenticate_bad_compat_token_does_not_echo_the_secret(tmp_path: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        authenticate(
            make_settings(tmp_path),
            MemoryDirectory(),
            x_role="admin",
            x_token="wrong-token-not-the-real-one",
        )
    assert exc.value.status_code == 401
    assert "token-admin" not in str(exc.value.detail)
    assert "wrong-token-not-the-real-one" not in str(exc.value.detail)


def test_authenticate_session_write_without_csrf_is_403(tmp_path: Path) -> None:
    store = MemoryDirectory()
    user = store.add_user(agent_user())
    token = "direct-session"
    csrf = "direct-csrf"
    store.add_session(token, user, csrf=csrf)
    with pytest.raises(HTTPException) as exc:
        authenticate(
            make_settings(tmp_path),
            store,
            request=make_request("POST", "/api/jobs"),
            hub_session=token,
            hub_csrf=csrf,
        )
    assert exc.value.status_code == 403
    assert token not in str(exc.value.detail)


def test_logs_redact_authorization_cookies_client_secret_and_jwt(caplog: pytest.LogCaptureFixture) -> None:
    install_secret_log_filter()
    caplog.set_level(logging.INFO)
    token = "eyJhbGciOiJSUzI1NiJ9.eyJlbWFpbCI6ImFkYUBleGFtcGxlLnRlc3QifQ.signaturevalue"
    logging.getLogger("app.auth_manager").info("Authorization: Bearer %s", "jh_agt_supersecret")
    logging.getLogger("app.auth_manager").info("Cookie: hub_session=%s", "session-secret")
    logging.getLogger("app.auth_manager").info("CF-Access-Client-Secret: %s", "client-secret-value")
    logging.getLogger("app.auth_manager").info("Cf-Access-Jwt-Assertion: %s", token)
    text = caplog.text
    assert "jh_agt_supersecret" not in text
    assert "session-secret" not in text
    assert "client-secret-value" not in text
    assert token not in text
    assert "signaturevalue" not in text


def test_middleware_sets_principal_and_keeps_public_paths(tmp_path: Path) -> None:
    store = MemoryDirectory()
    user = store.add_user(agent_user())
    secret = "jh_agt_middleware_secret"
    store.add_key(secret, user)
    token = "middleware-session"
    csrf = "middleware-csrf"
    store.add_session(token, user, csrf=csrf)
    app = FastAPI()
    app.add_middleware(AuthGateMiddleware)
    app.state.settings = make_settings(tmp_path)
    app.state.db = store

    @app.get("/health")
    def health(request: Request) -> dict:
        principal = getattr(request.state, "principal", None)
        return {"user_id": None if principal is None else principal.user_id}

    @app.get("/llms.txt")
    def llms() -> dict:
        return {"ok": True}

    @app.post("/api/auth/join")
    def join() -> dict:
        return {"ok": True}

    @app.get("/api/jobs")
    def jobs(request: Request) -> dict:
        principal = request.state.principal
        return {"user_id": principal.user_id, "account_id": principal.account_id}

    @app.post("/api/jobs")
    def create_job(request: Request) -> dict:
        return {"csrf_ok": request.state.principal.csrf_ok}

    @app.get("/admin")
    def admin_page() -> dict:
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/llms.txt").status_code == 200
    assert client.post("/api/auth/join").status_code == 200
    assert client.get("/health", headers={"Authorization": "Bearer jh_agt_not-a-real-key"}).status_code == 200
    denied = client.get("/api/jobs")
    assert denied.status_code == 401
    html = client.get("/admin", headers={"accept": "text/html"}, follow_redirects=False)
    assert html.status_code == 302
    assert html.headers["location"].startswith("/login?next=")
    authed = client.get("/api/jobs", headers={"Authorization": f"Bearer {secret}"})
    assert authed.status_code == 200
    assert authed.json() == {"user_id": user["id"], "account_id": "acc_user"}
    csrf_denied = client.post("/api/jobs", cookies={"hub_session": token, "hub_csrf": csrf})
    assert csrf_denied.status_code == 403
    assert "jh_" not in csrf_denied.text


def test_candidate_gate_reads_state_principal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str | None] = {}

    def status(_settings, _db, tenant=None):
        seen["account"] = None if tenant is None else tenant.account_id
        return {"onboarded": False}

    def explode(*_args, **_kwargs):
        raise AssertionError("authenticate called")

    monkeypatch.setattr("app.gates.hub_public_candidate_status", status)
    monkeypatch.setattr("app.auth.authenticate", explode)
    monkeypatch.setattr("app.gates.authenticate", explode, raising=False)
    store = MemoryDirectory()
    user = store.add_user(agent_user(account_id="acc_user"))
    secret = "jh_agt_gate_secret"
    store.add_key(secret, user, account_id="acc_from_key_row")
    app = FastAPI()
    app.add_middleware(CandidateGateMiddleware)
    app.add_middleware(AuthGateMiddleware)
    app.state.settings = make_settings(tmp_path)
    app.state.db = store

    @app.get("/api/jobs")
    def jobs(request: Request) -> dict:
        return {"user_id": request.state.principal.user_id}

    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/api/jobs", headers={"Authorization": f"Bearer {secret}"})
    assert res.status_code == 409
    assert seen["account"] == "acc_user"


def test_require_principal_reads_state_and_does_not_authenticate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args, **_kwargs):
        raise AssertionError("authenticate called")

    monkeypatch.setattr("app.auth.authenticate", explode)
    user = agent_user()
    from app.auth import Principal

    principal = Principal(
        role="discovery",
        actor="Ada",
        user_id=user["id"],
        track="discovery",
        kind="agent",
        auth="agent_key",
        account_id=user["account_id"],
    )
    request = make_request("GET", "/api/jobs")
    request.state.principal = principal
    dep = require_principal(make_settings(tmp_path), MemoryDirectory())
    assert asyncio.run(dep(request)) is principal
    bare = make_request("GET", "/api/jobs")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(dep(bare))
    assert exc.value.status_code == 401


def test_optional_principal_and_activity_wrapper_read_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args, **_kwargs):
        raise AssertionError("authenticate called")

    monkeypatch.setattr("app.auth.authenticate", explode)
    from app.auth import Principal

    state_principal = Principal(
        role="discovery",
        actor="Ada",
        user_id="usr_state",
        track="discovery",
        kind="agent",
        auth="agent_key",
        account_id="acc_user",
    )
    other = Principal(
        role="apply",
        actor="Other",
        user_id="usr_other",
        track="application",
        kind="agent",
        auth="session",
        account_id="acc_other",
    )
    recorded: dict[str, str] = {}

    def fake_record(_db, principal, _request, **_kwargs):
        recorded["user_id"] = principal.user_id
        return None

    monkeypatch.setattr("app.presence.record_activity", fake_record)
    request = make_request("GET", "/api/jobs")
    request.state.principal = state_principal
    optional = optional_principal(make_settings(tmp_path), MemoryDirectory())
    assert asyncio.run(optional(request)) is state_principal
    empty = make_request("GET", "/api/jobs")
    assert asyncio.run(optional(empty)) is None
    wrapper = wrap_principal_with_activity(lambda: None, MemoryDirectory())
    result = asyncio.run(wrapper(request, other))
    assert result is state_principal
    assert recorded["user_id"] == "usr_state"
