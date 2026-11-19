"""One ordered auth pass per request. The first method that applies wins.

A second method that resolves a different user id is a 401. None means that
method does not apply. Legacy X-Role + X-Token still runs when no configured
method applies, so existing compat clients keep working.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Protocol

from fastapi import HTTPException
from starlette.requests import Request

from app.auth import (
    Principal,
    _parse_ts,
    _principal_from_user,
    _safe_equals,
    _unauthorized,
    authenticate_compat,
)
from app.bootstrap import sha256_hex
from app.identity import session_expiry
from app.jwt_rs256 import JwtError, decode_rs256
from app.settings import Settings

_SECRET_HEADER = re.compile(
    r"(?i)\b(authorization|cf-access-client-secret|cf-access-jwt-assertion|cookie)\b\s*[:=]\s*\S+"
)
_BEARER = re.compile(r"(?i)\bbearer\s+\S+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_COOKIE_PAIR = re.compile(r"(?i)\b(hub_session|hub_csrf)\s*=\s*[^;\s]+")
_HUB_KEY = re.compile(r"\bjh_(?:agt|own|boot|inv)_[A-Za-z0-9._~+/-]+")
_SPECIAL_KEYS = ("jh_boot_", "jh_inv_")
_FILTER_INSTALLED = False

CSRF_DETAIL = "missing or invalid X-CSRF (required for cookie-authenticated writes)"


class AuthMethod(Protocol):
    name: str

    def match(self, request: Request) -> Principal | None:
        """Return a principal, or None when this method does not apply."""


class AuthConflict(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=401, detail="conflicting credentials")


def redact_log_text(text: str) -> str:
    text = _SECRET_HEADER.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    text = _BEARER.sub("Bearer [redacted]", text)
    text = _JWT.sub("[redacted]", text)
    text = _COOKIE_PAIR.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    text = _HUB_KEY.sub("[redacted]", text)
    return text


def install_secret_log_filter() -> None:
    """Redact credentials anywhere a log line is formatted. Idempotent."""
    global _FILTER_INSTALLED
    if _FILTER_INSTALLED:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        try:
            rendered = record.getMessage()
        except Exception:
            return record
        record.msg = redact_log_text(rendered)
        record.args = None
        return record

    logging.setLogRecordFactory(factory)
    _FILTER_INSTALLED = True


def access_issuer(team_domain: str) -> str:
    host = team_domain.strip().rstrip("/")
    if host.startswith("https://"):
        host = host[len("https://") :]
    elif host.startswith("http://"):
        host = host[len("http://") :]
    host = host.split("/", 1)[0]
    if "." not in host:
        host = f"{host}.cloudflareaccess.com"
    return f"https://{host}"


def _presented_role_token(request: Request) -> bool:
    return bool(
        (request.headers.get("x-role") or "").strip()
        and (request.headers.get("x-token") or "").strip()
    )


def _presented_hub_key(request: Request) -> str:
    header_key = (request.headers.get("x-hub-key") or "").strip()
    if header_key:
        return header_key
    authorization = (request.headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return ""


def _actor(request: Request) -> str | None:
    actor = (request.headers.get("x-actor") or "").strip()
    return actor or None


class HubKeyMethod:
    name = "hub_key"

    def __init__(self, db: Any) -> None:
        self._db = db

    def match(self, request: Request) -> Principal | None:
        secret = _presented_hub_key(request)
        if not secret:
            return None
        if secret.startswith(_SPECIAL_KEYS):
            raise _unauthorized(
                "this key cannot authenticate API calls; use join or bootstrap endpoints"
            )
        row = self._db.get_api_key_by_hash(sha256_hex(secret))
        if not row or row.get("revoked_at"):
            raise _unauthorized("invalid API key")
        user = self._db.get_user(row["user_id"])
        if user is None:
            raise _unauthorized("invalid API key")
        if user["kind"] == "admin":
            auth = "admin_key"
        elif user["kind"] == "owner":
            auth = "owner_key"
        else:
            auth = "agent_key"
        # account_id is taken from the user row inside _principal_from_user.
        return _principal_from_user(user, auth=auth, actor_override=_actor(request))


class SessionMethod:
    name = "session"

    def __init__(self, db: Any) -> None:
        self._db = db

    def match(self, request: Request) -> Principal | None:
        # A hub key, or X-Role plus X-Token, is the caller. The cookie is not a
        # second identity, matching the previous short-circuit order.
        if _presented_hub_key(request) or _presented_role_token(request):
            return None
        token = (request.cookies.get("hub_session") or "").strip()
        if not token:
            return None
        session = self._db.get_session_by_token_hash(sha256_hex(token))
        if session is None:
            raise _unauthorized("invalid session")
        expires = _parse_ts(session.get("expires_at"))
        if expires is not None and expires.timestamp() < time.time():
            self._db.delete_session(session["id"])
            raise _unauthorized("session expired")
        user = self._db.get_user(session["user_id"])
        if user is None:
            raise _unauthorized("invalid session")
        csrf_ok = True
        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            cookie_csrf = (request.cookies.get("hub_csrf") or "").strip()
            header_csrf = (request.headers.get("x-csrf") or "").strip()
            stored = str(session.get("csrf_hash") or "")
            csrf_ok = bool(
                cookie_csrf
                and header_csrf
                and _safe_equals(cookie_csrf, header_csrf)
                and stored
                and _safe_equals(stored, sha256_hex(header_csrf))
            )
        if csrf_ok:
            self._db.touch_session(session["id"], session_expiry())
        built = _principal_from_user(user, auth="session", actor_override=_actor(request))
        return Principal(
            role=built.role,
            actor=built.actor,
            user_id=built.user_id,
            track=built.track,
            kind=built.kind,
            auth="session",
            csrf_ok=csrf_ok,
            account_id=built.account_id,
        )


class AccessJwtMethod:
    name = "access_jwt"

    def __init__(self, settings: Settings, db: Any) -> None:
        self._settings = settings
        self._db = db
        team = settings.access_team_domain.strip()
        audience = settings.access_aud.strip()
        self._enabled = bool(team and audience)
        self._issuer = access_issuer(team) if self._enabled else ""
        self._audience = audience

    def match(self, request: Request) -> Principal | None:
        if not self._enabled:
            return None
        token = (request.headers.get("cf-access-jwt-assertion") or "").strip()
        if not token:
            return None
        if not self._settings.access_jwt_public_key.strip():
            raise _unauthorized("invalid access token")
        try:
            claims = decode_rs256(token, self._settings.access_jwt_public_key)
        except JwtError:
            raise _unauthorized("invalid access token") from None
        if claims.get("iss") != self._issuer:
            raise _unauthorized("invalid access token")
        audience = claims.get("aud")
        audiences = audience if isinstance(audience, list) else [audience]
        if self._audience not in audiences:
            raise _unauthorized("invalid access token")
        exp = claims.get("exp")
        if isinstance(exp, bool) or not isinstance(exp, (int, float)) or time.time() >= float(exp):
            raise _unauthorized("invalid access token")
        email = claims.get("email")
        if not isinstance(email, str) or not email.strip():
            raise _unauthorized("invalid access token")
        user = self._db.get_user_by_email(email)
        if user is None:
            raise _unauthorized("invalid access token")
        return _principal_from_user(user, auth="access_jwt", actor_override=_actor(request))


class CompatMethod:
    name = "compat"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def match(self, request: Request) -> Principal | None:
        role = (request.headers.get("x-role") or "").strip()
        token = (request.headers.get("x-token") or "").strip()
        if not role and not token:
            return None
        return authenticate_compat(self._settings, role, token, request.headers.get("x-actor"))


_BUILDERS = {
    "hub_key": lambda settings, db: HubKeyMethod(db),
    "session": lambda settings, db: SessionMethod(db),
    "access_jwt": lambda settings, db: AccessJwtMethod(settings, db),
    "compat": lambda settings, db: CompatMethod(settings),
}


class AuthManager:
    def __init__(self, methods: list[AuthMethod], *, settings: Settings, db: Any) -> None:
        install_secret_log_filter()
        self.methods = methods
        self.settings = settings
        self.db = db

    @classmethod
    def from_settings(cls, settings: Settings, db: Any) -> AuthManager:
        raw = (settings.auth_methods or "").strip() or "hub_key,session"
        names = [part.strip() for part in raw.split(",") if part.strip()]
        methods: list[AuthMethod] = []
        for name in names:
            builder = _BUILDERS.get(name)
            if builder is None:
                raise ValueError(f"unknown auth method {name}")
            methods.append(builder(settings, db))
        return cls(methods, settings=settings, db=db)

    def resolve(self, request: Request) -> Principal | None:
        outcomes: list[tuple[str, Any]] = []
        for method in self.methods:
            try:
                principal = method.match(request)
            except HTTPException as exc:
                outcomes.append(("error", exc))
                continue
            if principal is None:
                continue
            outcomes.append(("ok", principal))
        if not outcomes:
            if any(method.name == "compat" for method in self.methods):
                return None
            return CompatMethod(self.settings).match(request)
        kind, value = outcomes[0]
        if kind == "error":
            raise value
        matched = [item for item_kind, item in outcomes if item_kind == "ok"]
        if len({item.user_id for item in matched}) > 1:
            raise AuthConflict()
        return matched[0]


def request_for_credentials(
    *,
    method: str = "GET",
    authorization: str | None = None,
    x_hub_key: str | None = None,
    x_role: str | None = None,
    x_token: str | None = None,
    x_actor: str | None = None,
    x_csrf: str | None = None,
    hub_session: str | None = None,
    hub_csrf: str | None = None,
    cf_access_jwt: str | None = None,
) -> Request:
    """Build a request from already-extracted credentials. Values are not logged."""
    raw: list[tuple[bytes, bytes]] = []

    def add(name: str, value: str | None) -> None:
        if value:
            raw.append((name.encode("ascii"), value.encode("latin-1")))

    add("authorization", authorization)
    add("x-hub-key", x_hub_key)
    add("x-role", x_role)
    add("x-token", x_token)
    add("x-actor", x_actor)
    add("x-csrf", x_csrf)
    add("cf-access-jwt-assertion", cf_access_jwt)
    cookies: list[str] = []
    if hub_session:
        cookies.append(f"hub_session={hub_session}")
    if hub_csrf:
        cookies.append(f"hub_csrf={hub_csrf}")
    if cookies:
        raw.append((b"cookie", "; ".join(cookies).encode("latin-1")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": (method or "GET").upper(),
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": raw,
        "client": ("127.0.0.1", 0),
        "server": ("test", 80),
    }
    return Request(scope)
