"""Header auth: X-Role + X-Token. Tokens are per-role and never hardcoded."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.constants import ROLES
from app.settings import Settings


@dataclass(frozen=True)
class Principal:
    role: str
    actor: str


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def authenticate(
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
    return Principal(role=role, actor=actor)


def require_principal(settings: Settings):
    async def dependency(
        x_role: Annotated[str | None, Header()] = None,
        x_token: Annotated[str | None, Header()] = None,
        x_actor: Annotated[str | None, Header()] = None,
    ) -> Principal:
        return authenticate(settings, x_role, x_token, x_actor)

    return dependency
