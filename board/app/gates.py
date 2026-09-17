"""Block Hub work until a truthful candidate profile is onboarded."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from app.profile import candidate_onboarded

CANDIDATE_REQUIRED_CODE = "candidate_required"

_ALLOW_EXACT = frozenset(
    {
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
        if settings is None or candidate_onboarded(settings):
            return await call_next(request)
        if request.method == "GET" and wants_html(request):
            return RedirectResponse(url="/onboarding", status_code=302)
        return JSONResponse(status_code=409, content={"detail": candidate_required_payload()})
