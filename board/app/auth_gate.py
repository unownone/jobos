"""Server-side auth gate: unauthenticated clients cannot see Hub data.

Public marketing/login/join/health and A2A discovery stay reachable.
Job board, candidate, admin, packs, and every other data surface require a
session, Bearer/X-Hub-Key, or compat X-Role + X-Token. Missing creds never
receive job/candidate bodies.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlparse

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from app.auth_manager import AuthConflict, AuthManager, CSRF_DETAIL, install_secret_log_filter
from app.gates import wants_html

AUTH_REQUIRED = "authentication required"
_SECRET_MARKERS = ("jh_boot_", "jh_agt_", "jh_own_", "jh_inv_", "password_hash", "key_hash")
_SECRET_DETAIL_KEYS = frozenset(
    {"password", "password_hash", "api_key", "token", "secret", "authorization", "key_hash"}
)

_PUBLIC_EXACT = frozenset(
    {
        "/",
        "/start",
        "/health",
        "/livez",
        "/ready",
        "/favicon.ico",
        "/login",
        "/admin/signup",
        "/api/auth/bootstrap",
        "/api/auth/login",
        "/api/auth/signup",
        "/api/auth/join",
        "/a2a",
        "/api/registry/catalog",
        "/llms.txt",
        "/agents.txt",
        "/static/hub.css",
    }
)

_PUBLIC_PREFIXES = (
    "/join/",
    "/api/join/",
    "/.well-known/",
    "/a2a/",
    "/brand/",
)
_PUBLIC_STATIC_SUFFIXES = frozenset(
    {".css", ".js", ".map", ".woff", ".woff2", ".png", ".svg", ".ico", ".jpg", ".webp"}
)


def redact_secrets(value: Any) -> Any:
    """Drop secret fields and Hub key prefixes from error payloads."""
    if isinstance(value, dict):
        return {
            key: redact_secrets(item)
            for key, item in value.items()
            if key.lower() not in _SECRET_DETAIL_KEYS
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in _SECRET_MARKERS):
            return AUTH_REQUIRED
        return value
    return value


def path_is_public(path: str) -> bool:
    cleaned = path.rstrip("/") or "/"
    if cleaned in _PUBLIC_EXACT or path in _PUBLIC_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES):
        return True
    if path.startswith("/static/"):
        suffix = ""
        if "." in path.rsplit("/", 1)[-1]:
            suffix = "." + path.rsplit(".", 1)[-1].lower()
        return suffix in _PUBLIC_STATIC_SUFFIXES
    return False


def safe_next_path(raw: str | None) -> str:
    """Relative path only. Blocks open redirects and credential-bearing URLs."""
    text = (raw or "").strip() or "/"
    if "://" in text or "\\" in text or "\n" in text or "\r" in text:
        return "/"
    parsed = urlparse(text)
    if parsed.scheme or parsed.netloc:
        return "/"
    path = parsed.path or "/"
    if not path.startswith("/") or path.startswith("//"):
        return "/"
    if path.startswith("/login") or path.startswith("/admin/signup"):
        return "/"
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


def unauthenticated_response(request: Request, *, detail: Any = AUTH_REQUIRED) -> Response:
    safe = redact_secrets(detail) if detail is not None else AUTH_REQUIRED
    if request.method in {"GET", "HEAD"} and wants_html(request):
        nxt = safe_next_path(str(request.url.path))
        query = request.url.query
        if query and nxt == request.url.path:
            nxt = safe_next_path(f"{request.url.path}?{query}")
        return RedirectResponse(
            url=f"/login?next={quote(nxt, safe='/?')}",
            status_code=302,
        )
    return JSONResponse(status_code=401, content={"detail": safe})


class AuthGateMiddleware(BaseHTTPMiddleware):
    """Reject anonymous access before route handlers load sensitive payloads."""

    async def dispatch(self, request: Request, call_next) -> Response:
        install_secret_log_filter()
        if request.method == "OPTIONS":
            request.state.principal = None
            return await call_next(request)
        path = request.url.path
        public = path_is_public(path)
        settings = getattr(request.app.state, "settings", None)
        db = getattr(request.app.state, "db", None)
        if settings is None or db is None:
            request.state.principal = None
            if public:
                return await call_next(request)
            return unauthenticated_response(request)
        manager = AuthManager.from_settings(settings, db)
        try:
            principal = manager.resolve(request)
        except AuthConflict as exc:
            request.state.principal = None
            return unauthenticated_response(request, detail=exc.detail)
        except HTTPException as exc:
            request.state.principal = None
            if public:
                return await call_next(request)
            if exc.status_code == 401:
                return unauthenticated_response(request, detail=exc.detail)
            if exc.status_code in {403, 503}:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": redact_secrets(exc.detail)},
                )
            raise
        if principal is not None and not principal.csrf_ok:
            if public:
                principal = None
            else:
                request.state.principal = None
                return JSONResponse(status_code=403, content={"detail": CSRF_DETAIL})
        request.state.principal = principal
        if public or principal is not None:
            return await call_next(request)
        return unauthenticated_response(request)
