"""Auth: session cookie, Bearer / X-Hub-Key, and compat X-Role + X-Token."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, Request, status

from app.constants import ROLE_TO_TRACK, ROLES, role_for_track
from app.db import BoardDB
from app.settings import Settings
from app.tenant import COMPAT_ACCOUNT_ID, TenantContext


@dataclass(frozen=True)
class Principal:
    role: str
    actor: str
    user_id: str | None = None
    track: str | None = None
    kind: str | None = None
    auth: str = "compat_role"
    csrf_ok: bool = True
    account_id: str | None = None

    @property
    def tenant(self) -> TenantContext:
        return TenantContext(self.account_id or COMPAT_ACCOUNT_ID)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def has_request_credentials(request: Request) -> bool:
    """True when the request carries any Hub auth material (not invite secrets)."""
    return any(
        [
            (request.headers.get("authorization") or "").strip(),
            (request.headers.get("x-hub-key") or "").strip(),
            (request.headers.get("x-role") or "").strip(),
            (request.headers.get("x-token") or "").strip(),
            (request.cookies.get("hub_session") or "").strip(),
        ]
    )


def _safe_equals(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return hmac.compare_digest(left, right)


def _principal_from_user(user: dict, *, auth: str, actor_override: str | None = None) -> Principal:
    if user.get("disabled_at"):
        raise _unauthorized("user disabled")
    kind = user["kind"]
    track = user.get("track")
    if kind == "admin":
        role = "admin"
        track = None
    elif kind == "viewer":
        role = "maintenance"
        track = None
    else:
        role = role_for_track(track) or ""
        if not role:
            raise _unauthorized("user has no track")
    actor = actor_override or user.get("display_name") or user.get("email") or user["id"]
    return Principal(
        role=role,
        actor=str(actor),
        user_id=user["id"],
        track=track,
        kind=kind,
        auth=auth,
        account_id=str(user.get("account_id") or COMPAT_ACCOUNT_ID),
    )


def authenticate_compat(
    settings: Settings,
    x_role: str | None,
    x_token: str | None,
    x_actor: str | None = None,
) -> Principal:
    role = (x_role or "").strip().lower()
    token = (x_token or "").strip()
    if not role or not token:
        raise _unauthorized("missing X-Role or X-Token")
    if role not in ROLES:
        raise _unauthorized("unknown role")
    expected = settings.tokens.get(role, "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="role token is not configured; maintainer must run scripts/board_gen_tokens.py",
        )
    if not hmac.compare_digest(token, expected):
        raise _unauthorized("invalid token for role")
    actor = (x_actor or "").strip()
    return Principal(
        role=role,
        actor=actor,
        user_id=None,
        track=ROLE_TO_TRACK.get(role),
        kind="compat",
        auth="compat_role",
        account_id=COMPAT_ACCOUNT_ID,
    )


def _credential(explicit: str | None, fallback: str | None) -> str | None:
    if explicit is not None:
        return explicit
    return fallback


def authenticate(
    settings: Settings,
    db: BoardDB,
    *,
    request: Request | None = None,
    authorization: str | None = None,
    x_hub_key: str | None = None,
    x_role: str | None = None,
    x_token: str | None = None,
    x_actor: str | None = None,
    x_csrf: str | None = None,
    hub_session: str | None = None,
    hub_csrf: str | None = None,
) -> Principal:
    # Deferred: AuthManager imports Principal and the helpers defined above.
    from app.auth_manager import AuthManager, CSRF_DETAIL, request_for_credentials

    header = request.headers.get if request is not None else lambda _name: None
    cookie = request.cookies.get if request is not None else lambda _name: None
    synthetic = request_for_credentials(
        method=request.method if request is not None else "GET",
        authorization=_credential(authorization, header("authorization")),
        x_hub_key=_credential(x_hub_key, header("x-hub-key")),
        x_role=_credential(x_role, header("x-role")),
        x_token=_credential(x_token, header("x-token")),
        x_actor=_credential(x_actor, header("x-actor")),
        x_csrf=_credential(x_csrf, header("x-csrf")),
        hub_session=_credential(hub_session, cookie("hub_session")),
        hub_csrf=_credential(hub_csrf, cookie("hub_csrf")),
        cf_access_jwt=header("cf-access-jwt-assertion"),
    )
    principal = AuthManager.from_settings(settings, db).resolve(synthetic)
    if principal is None:
        raise _unauthorized("missing credentials")
    if not principal.csrf_ok:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=CSRF_DETAIL)
    return principal


def require_principal(settings: Settings, db: BoardDB):
    """Read the principal the auth middleware already stored. Does not authenticate again."""

    async def dependency(request: Request) -> Principal:
        principal = getattr(request.state, "principal", None)
        if principal is None:
            raise _unauthorized("authentication required")
        if not principal.csrf_ok:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="missing or invalid X-CSRF (required for cookie-authenticated writes)",
            )
        return principal

    return dependency


def optional_principal(settings: Settings, db: BoardDB):
    """A2A JSON-RPC: missing creds stay None. Reads the middleware principal."""

    async def dependency(request: Request) -> Principal | None:
        principal = getattr(request.state, "principal", None)
        if principal is None or not principal.csrf_ok:
            return None
        return principal

    return dependency


def require_admin(principal: Principal) -> None:
    if principal.kind != "admin" and principal.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    if principal.kind == "viewer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    if principal.auth == "compat_role" and principal.role == "admin":
        return
    if principal.kind != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")


def require_owner_or_admin(principal: Principal) -> None:
    if principal.kind == "admin" or principal.role == "admin":
        return
    if principal.kind == "owner":
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="only a track owner or admin can mint agents",
    )
