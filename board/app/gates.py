"""Block Hub work until a truthful candidate profile is onboarded."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from app.auth import authenticate, has_request_credentials
from app.profile import candidate_onboarded
from app.tenant import COMPAT_ACCOUNT_ID

CANDIDATE_REQUIRED_CODE = "candidate_required"

_ALLOW_EXACT = frozenset(
    {
        "/",
        "/start",
        "/health",
        "/ready",
        "/favicon.ico",
        "/llms.txt",
        "/agents.txt",
        "/login",
        "/admin/signup",
        "/onboarding",
        "/api/auth/bootstrap",
        "/api/auth/login",
        "/api/auth/signup",
        "/api/auth/logout",
        "/api/auth/me",
        "/api/whoami",
        "/api/candidate",
        "/api/candidate/public",
        "/api/candidate/resume",
        "/api/candidate/status",
        "/api/candidate/template",
        "/api/registry/catalog",
    }
)

_ALLOW_PREFIXES = (
    "/static/",
    "/brand/",
    "/.well-known/",
    "/a2a",
    "/api/join/",
    "/join/",
)


def candidate_required_payload() -> dict[str, str]:
    return {
        "code": CANDIDATE_REQUIRED_CODE,
        "message": "Onboard the candidate profile before using the Hub. Do not invent one.",
        "onboarding_url": "/onboarding",
    }


def path_is_open(path: str) -> bool:
    cleaned = path.rstrip("/") or "/"
    if cleaned in _ALLOW_EXACT or path in _ALLOW_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in _ALLOW_PREFIXES)


def wants_html(request: Request) -> bool:
    accept = request.headers.get("accept") or ""
    if "text/html" in accept:
        return True
    dest = request.headers.get("sec-fetch-dest") or ""
    return dest in {"document", "iframe"}


class CandidateGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path_is_open(path):
            return await call_next(request)
        settings = getattr(request.app.state, "settings", None)
        db = getattr(request.app.state, "db", None)
        tenant = None
        if settings is not None and db is not None and has_request_credentials(request):
            try:
                principal = authenticate(
                    settings,
                    db,
                    request=None,
                    authorization=request.headers.get("authorization"),
                    x_hub_key=request.headers.get("x-hub-key"),
                    x_role=request.headers.get("x-role"),
                    x_token=request.headers.get("x-token"),
                    x_actor=request.headers.get("x-actor"),
                    hub_session=request.cookies.get("hub_session"),
                    hub_csrf=request.cookies.get("hub_csrf"),
                )
                tenant = principal.tenant
            except Exception:
                tenant = None
        onboarded = False
        if settings is not None:
            onboarded = candidate_onboarded(settings, db, tenant=tenant)
            if not onboarded and (tenant is None or tenant.account_id == COMPAT_ACCOUNT_ID):
                onboarded = candidate_onboarded(settings)
        if settings is None or onboarded:
            return await call_next(request)
        if request.method == "GET" and wants_html(request):
            return RedirectResponse(url="/onboarding", status_code=302)
        return JSONResponse(status_code=409, content={"detail": candidate_required_payload()})
