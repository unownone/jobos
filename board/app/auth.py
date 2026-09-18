"""Auth: session cookie, Bearer / X-Hub-Key, and compat X-Role + X-Token."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Cookie, Header, HTTPException, Request, status

from app.bootstrap import sha256_hex
from app.constants import ROLE_TO_TRACK, ROLES, role_for_track
from app.db import BoardDB
from app.identity import session_expiry
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


def _extract_bearer(authorization: str | None, x_hub_key: str | None) -> str:
    if x_hub_key and x_hub_key.strip():
        return x_hub_key.strip()
    auth = (authorization or "").strip()
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return ""


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
    bearer = _extract_bearer(authorization, x_hub_key)
    if bearer:
        if bearer.startswith("jh_boot_") or bearer.startswith("jh_inv_"):
            raise _unauthorized("this key cannot authenticate API calls; use join or bootstrap endpoints")
        row = db.get_api_key_by_hash(sha256_hex(bearer))
        if not row or row.get("revoked_at"):
            raise _unauthorized("invalid API key")
        user = db.get_user(row["user_id"])
        if user is None:
            raise _unauthorized("invalid API key")
        auth = "owner_key" if user["kind"] == "owner" else "agent_key"
        if user["kind"] == "admin":
            auth = "admin_key"
        return _principal_from_user(user, auth=auth, actor_override=x_actor or None)

    if (x_role or "").strip() and (x_token or "").strip():
        return authenticate_compat(settings, x_role, x_token, x_actor)

    session_token = (hub_session or "").strip()
    if session_token:
        sess = db.get_session_by_token_hash(sha256_hex(session_token))
        if sess is None:
            raise _unauthorized("invalid session")
        expires = _parse_ts(sess.get("expires_at"))
        if expires and datetime.now(timezone.utc) > expires:
            db.delete_session(sess["id"])
            raise _unauthorized("session expired")
        user = db.get_user(sess["user_id"])
        if user is None:
            raise _unauthorized("invalid session")
        method = (request.method if request is not None else "GET").upper()
        csrf_ok = True
        if method not in {"GET", "HEAD", "OPTIONS"}:
            cookie_csrf = (hub_csrf or "").strip()
            header_csrf = (x_csrf or "").strip()
            stored = str(sess.get("csrf_hash") or "")
            csrf_ok = bool(
                cookie_csrf
                and header_csrf
                and _safe_equals(cookie_csrf, header_csrf)
                and stored
                and _safe_equals(stored, sha256_hex(header_csrf))
            )
            if not csrf_ok:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="missing or invalid X-CSRF (required for cookie-authenticated writes)",
                )
        db.touch_session(sess["id"], session_expiry())
        principal = _principal_from_user(user, auth="session", actor_override=x_actor or None)
        return Principal(
            role=principal.role,
            actor=principal.actor,
            user_id=principal.user_id,
            track=principal.track,
            kind=principal.kind,
            auth="session",
            csrf_ok=csrf_ok,
            account_id=principal.account_id,
        )

    return authenticate_compat(settings, x_role, x_token, x_actor)


def require_principal(settings: Settings, db: BoardDB):
    async def dependency(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        x_hub_key: Annotated[str | None, Header(alias="X-Hub-Key")] = None,
        x_role: Annotated[str | None, Header()] = None,
        x_token: Annotated[str | None, Header()] = None,
        x_actor: Annotated[str | None, Header()] = None,
        x_csrf: Annotated[str | None, Header(alias="X-CSRF")] = None,
        hub_session: Annotated[str | None, Cookie()] = None,
        hub_csrf: Annotated[str | None, Cookie()] = None,
    ) -> Principal:
        return authenticate(
            settings,
            db,
            request=request,
            authorization=authorization,
            x_hub_key=x_hub_key,
            x_role=x_role,
            x_token=x_token,
            x_actor=x_actor,
            x_csrf=x_csrf,
            hub_session=hub_session,
            hub_csrf=hub_csrf,
        )

    return dependency


def optional_principal(settings: Settings, db: BoardDB):
    """A2A JSON-RPC: missing/invalid creds become None instead of HTTP 401."""

    async def dependency(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        x_hub_key: Annotated[str | None, Header(alias="X-Hub-Key")] = None,
        x_role: Annotated[str | None, Header()] = None,
        x_token: Annotated[str | None, Header()] = None,
        x_actor: Annotated[str | None, Header()] = None,
        x_csrf: Annotated[str | None, Header(alias="X-CSRF")] = None,
        hub_session: Annotated[str | None, Cookie()] = None,
        hub_csrf: Annotated[str | None, Cookie()] = None,
    ) -> Principal | None:
        if not has_request_credentials(request):
            return None
        try:
            return authenticate(
                settings,
                db,
                request=request,
                authorization=authorization,
                x_hub_key=x_hub_key,
                x_role=x_role,
                x_token=x_token,
                x_actor=x_actor,
                x_csrf=x_csrf,
                hub_session=hub_session,
                hub_csrf=hub_csrf,
            )
        except HTTPException as exc:
            if exc.status_code in {401, 403}:
                return None
            raise

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
