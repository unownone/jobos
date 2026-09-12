"""Invite join, owner/agent keys, session cookies. Secrets never logged."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Response, status

from app.bootstrap import SESSION_IDLE, new_id, public_base, sha256_hex
from app.constants import (
    INVITE_MODES,
    METADATA_KNOWN_KEYS,
    TRACKS,
    canonical_track,
    role_for_track,
)
from app.db import BoardDB, public_user, utc_now
from app.pack import hub_pack_fields, join_onboarding_section
from app.profile import candidate_status, public_candidate_for_settings
from app.settings import Settings

COOKIE_SESSION = "hub_session"
COOKIE_CSRF = "hub_csrf"
DEFAULT_MAX_REDEMPTIONS = 8
DEFAULT_TTL_HOURS = 72
DEFAULT_MODE = "owner_then_agents"


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


def iso_future(hours: float) -> str:
    when = datetime.now(timezone.utc) + timedelta(hours=hours)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def session_expiry() -> str:
    return iso_future(SESSION_IDLE.total_seconds() / 3600)


def key_prefix(plain: str) -> str:
    if len(plain) <= 16:
        return plain[:4] + "…" + plain[-4:]
    return plain[:10] + "…" + plain[-4:]


def mint_owner_key(track: str) -> str:
    return f"jh_own_{track}_{secrets.token_urlsafe(24)}"


def mint_agent_key(user_id: str) -> str:
    slug = user_id.replace("usr_", "")[:16]
    return f"jh_agt_{slug}_{secrets.token_urlsafe(24)}"


def mint_invite_secret() -> str:
    return secrets.token_urlsafe(32)


def invite_token(invite_id: str, secret: str) -> str:
    return f"jh_inv_{invite_id}.{secret}"


def parse_invite_token(raw: str) -> tuple[str | None, str | None]:
    text = raw.strip()
    if text.startswith("jh_inv_"):
        rest = text[len("jh_inv_") :]
        if "." in rest:
            invite_id, secret = rest.split(".", 1)
            return invite_id, secret
    return None, None


def join_url(settings: Settings, invite_id: str, secret: str) -> str:
    return f"{public_base(settings)}/join/{invite_id}?s={secret}"


def normalize_metadata(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="metadata must be an object")
    out: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in raw.items():
        if key in METADATA_KNOWN_KEYS or key == "extra":
            out[str(key)] = value
        else:
            extra[str(key)] = value
    if extra:
        merged_extra = dict(out.get("extra") or {})
        if isinstance(merged_extra, dict):
            merged_extra.update(extra)
            out["extra"] = merged_extra
        else:
            out["extra"] = extra
    return out


def public_invite(row: dict[str, Any], *, include_hash: bool = False) -> dict[str, Any]:
    payload = {
        "id": row["id"],
        "track": row["track"],
        "mode": row["mode"],
        "max_redemptions": row["max_redemptions"],
        "redemptions": row["redemptions"],
        "expires_at": row["expires_at"],
        "revoked_at": row["revoked_at"],
        "allow_multiple_owners": row["allow_multiple_owners"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "remaining": max(0, int(row["max_redemptions"]) - int(row["redemptions"])),
    }
    if include_hash:
        payload["secret_hash"] = row["secret_hash"]
    return payload


def invite_status_error(row: dict[str, Any]) -> HTTPException | None:
    if row.get("revoked_at"):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invite revoked")
    expires = _parse_ts(row.get("expires_at"))
    if expires and datetime.now(timezone.utc) > expires:
        return HTTPException(status_code=status.HTTP_410_GONE, detail="invite expired")
    if int(row["redemptions"]) >= int(row["max_redemptions"]):
        return HTTPException(status_code=status.HTTP_410_GONE, detail="invite max redemptions reached")
    return None


def verify_invite_secret(row: dict[str, Any], secret: str) -> bool:
    if not secret:
        return False
    expected = str(row.get("secret_hash") or "")
    return secrets.compare_digest(expected, sha256_hex(secret))


def set_session_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    response.set_cookie(
        key=COOKIE_SESSION,
        value=session_token,
        httponly=True,
        samesite="lax",
        max_age=int(SESSION_IDLE.total_seconds()),
        path="/",
    )
    response.set_cookie(
        key=COOKIE_CSRF,
        value=csrf_token,
        httponly=False,
        samesite="lax",
        max_age=int(SESSION_IDLE.total_seconds()),
        path="/",
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(COOKIE_SESSION, path="/")
    response.delete_cookie(COOKIE_CSRF, path="/")


def create_user_session(db: BoardDB, user_id: str) -> tuple[str, str]:
    session_plain = secrets.token_urlsafe(32)
    csrf_plain = secrets.token_urlsafe(32)
    db.create_session(
        session_id=new_id("ses_"),
        user_id=user_id,
        token_hash=sha256_hex(session_plain),
        expires_at=session_expiry(),
        csrf_hash=sha256_hex(csrf_plain),
    )
    return session_plain, csrf_plain


def create_invite(
    db: BoardDB,
    *,
    track: str,
    mode: str | None,
    max_redemptions: int | None,
    ttl_hours: float | None,
    allow_multiple_owners: bool,
    created_by: str | None,
) -> tuple[dict[str, Any], str]:
    canon = canonical_track(track)
    if canon not in TRACKS:
        raise HTTPException(status_code=422, detail="track must be discovery|application|outreach|maintenance")
    invite_mode = (mode or DEFAULT_MODE).strip()
    if invite_mode not in INVITE_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {list(INVITE_MODES)}")
    cap = DEFAULT_MAX_REDEMPTIONS if max_redemptions is None else int(max_redemptions)
    if cap < 1 or cap > 64:
        raise HTTPException(status_code=422, detail="max_redemptions must be 1–64")
    hours = DEFAULT_TTL_HOURS if ttl_hours is None else float(ttl_hours)
    if hours <= 0 or hours > 24 * 30:
        raise HTTPException(status_code=422, detail="ttl_hours must be > 0 and ≤ 720")
    invite_id = new_id("inv_")
    secret = mint_invite_secret()
    row = db.insert_invite(
        invite_id=invite_id,
        track=canon,
        mode=invite_mode,
        secret_hash=sha256_hex(secret),
        max_redemptions=cap,
        expires_at=iso_future(hours),
        created_by=created_by,
        allow_multiple_owners=allow_multiple_owners,
    )
    return row, secret


def _choose_join_kind(db: BoardDB, invite: dict[str, Any]) -> str:
    mode = invite["mode"]
    owners = db.count_owners(invite["track"])
    if mode == "owner_only":
        if owners and not invite["allow_multiple_owners"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="track already has an owner",
            )
        return "owner"
    if mode == "agents_only":
        return "agent"
    # owner_then_agents
    if owners == 0:
        return "owner"
    if invite["allow_multiple_owners"] and owners >= 1:
        # still first-empty-owner then agents; extra owners only when admin
        # checkbox is set AND caller asks? Spec: extra owners require the flag.
        # Default remaining redemptions are agents once an owner exists.
        return "agent"
    return "agent"


def join_with_invite(
    db: BoardDB,
    *,
    invite_id: str,
    secret: str,
    display_name: str,
    metadata: dict[str, Any] | None,
    created_by: str | None = None,
    force_kind: str | None = None,
) -> dict[str, Any]:
    name = (display_name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="display_name is required")
    meta = normalize_metadata(metadata)
    db.begin_immediate()
    try:
        invite = db.get_invite(invite_id)
        if invite is None:
            db.rollback()
            raise HTTPException(status_code=404, detail="invite not found")
        if not verify_invite_secret(invite, secret):
            db.rollback()
            raise HTTPException(status_code=401, detail="invalid invite secret")
        err = invite_status_error(invite)
        if err:
            db.rollback()
            raise err
        kind = force_kind or _choose_join_kind(db, invite)
        if kind not in {"owner", "agent"}:
            db.rollback()
            raise HTTPException(status_code=422, detail="invalid kind")
        if kind == "owner":
            owners = db.count_owners(invite["track"])
            if owners and not invite["allow_multiple_owners"]:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="track already has an owner",
                )
        if invite["mode"] == "owner_only" and kind != "owner":
            db.rollback()
            raise HTTPException(status_code=403, detail="invite is owner_only")
        if invite["mode"] == "agents_only" and kind == "owner":
            db.rollback()
            raise HTTPException(status_code=403, detail="invite is agents_only")
        if db.display_name_taken(invite["track"], name):
            db.rollback()
            raise HTTPException(status_code=409, detail="display_name already used on this track")
        user_id = new_id("usr_")
        user = db.insert_user(
            user_id=user_id,
            kind=kind,
            track=invite["track"],
            email=None,
            password_hash=None,
            display_name=name,
            metadata=meta,
            created_by=created_by or invite["created_by"],
            commit=False,
        )
        plain = mint_owner_key(invite["track"]) if kind == "owner" else mint_agent_key(user_id)
        db.insert_api_key(
            key_id=new_id("key_"),
            user_id=user_id,
            prefix=key_prefix(plain),
            key_hash=sha256_hex(plain),
            commit=False,
        )
        db.redeem_invite(invite_id, commit=False)
        db.conn.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    db.add_event(
        job_id=None,
        actor_role=role_for_track(invite["track"]) or "admin",
        actor=name,
        action="join",
        note=f"{kind} joined track {invite['track']}",
        fields={"user_id": user_id, "track": invite["track"], "kind": kind, "invite_id": invite_id},
    )
    return {
        "user": public_user(user),
        "api_key": plain,
        "key_prefix": key_prefix(plain),
        "track": invite["track"],
        "kind": kind,
        "role": role_for_track(invite["track"]),
        "shown_once": True,
        "now": utc_now(),
    }


def mint_agent_for_owner(
    db: BoardDB,
    *,
    owner: dict[str, Any],
    display_name: str,
    metadata: dict[str, Any] | None,
    track: str | None = None,
) -> dict[str, Any]:
    name = (display_name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="display_name is required")
    target_track = track or owner.get("track")
    if owner.get("kind") == "admin":
        canon = canonical_track(target_track)
        if canon not in TRACKS:
            raise HTTPException(status_code=422, detail="admin must set track when minting an agent")
        target_track = canon
    elif owner.get("kind") != "owner":
        raise HTTPException(status_code=403, detail="only a track owner or admin can mint agents")
    else:
        target_track = owner["track"]
        if track and canonical_track(track) != target_track:
            raise HTTPException(status_code=403, detail="owner cannot mint agents for another track")
    if db.display_name_taken(target_track, name):
        raise HTTPException(status_code=409, detail="display_name already used on this track")
    user_id = new_id("usr_")
    user = db.insert_user(
        user_id=user_id,
        kind="agent",
        track=target_track,
        email=None,
        password_hash=None,
        display_name=name,
        metadata=normalize_metadata(metadata),
        created_by=owner["id"],
    )
    plain = mint_agent_key(user_id)
    db.insert_api_key(
        key_id=new_id("key_"),
        user_id=user_id,
        prefix=key_prefix(plain),
        key_hash=sha256_hex(plain),
    )
    db.add_event(
        job_id=None,
        actor_role=role_for_track(target_track) or "admin",
        actor=owner.get("display_name") or owner.get("email") or owner["id"],
        action="mint_agent",
        note="owner minted agent user",
        fields={"user_id": user_id, "track": target_track, "created_by": owner["id"]},
    )
    return {
        "user": public_user(user),
        "api_key": plain,
        "key_prefix": key_prefix(plain),
        "track": target_track,
        "kind": "agent",
        "role": role_for_track(target_track),
        "shown_once": True,
    }


def rotate_user_key(db: BoardDB, user: dict[str, Any]) -> dict[str, Any]:
    db.revoke_user_keys(user["id"])
    if user["kind"] == "owner":
        plain = mint_owner_key(user["track"])
    else:
        plain = mint_agent_key(user["id"])
    db.insert_api_key(
        key_id=new_id("key_"),
        user_id=user["id"],
        prefix=key_prefix(plain),
        key_hash=sha256_hex(plain),
    )
    db.add_event(
        job_id=None,
        actor_role=role_for_track(user.get("track")) or "admin",
        actor=user.get("display_name") or user["id"],
        action="rotate_key",
        fields={"user_id": user["id"]},
    )
    return {
        "user": public_user(user),
        "api_key": plain,
        "key_prefix": key_prefix(plain),
        "shown_once": True,
    }


def disable_agent(db: BoardDB, user: dict[str, Any]) -> dict[str, Any]:
    db.revoke_user_keys(user["id"])
    stored = db.disable_user(user["id"])
    db.add_event(
        job_id=None,
        actor_role=role_for_track(user.get("track")) or "admin",
        actor=user.get("display_name") or user["id"],
        action="disable_user",
        fields={"user_id": user["id"]},
    )
    return public_user(stored)


def join_payload(settings: Settings, invite: dict[str, Any]) -> dict[str, Any]:
    track = invite["track"]
    pack_fields = hub_pack_fields(settings)
    candidate = public_candidate_for_settings(settings)
    status = candidate_status(settings)
    onboarded = bool(status["onboarded"])
    return {
        "hub": {
            "public_url": public_base(settings),
            "version": "1",
            "pack_sha": pack_fields["pack_sha"],
            "git_sha": pack_fields["git_sha"],
        },
        "invite_id": invite["id"],
        "track": track,
        "mode": invite["mode"],
        "expires_at": invite["expires_at"],
        "max_redemptions": invite["max_redemptions"],
        "redemptions": invite["redemptions"],
        "remaining": max(0, int(invite["max_redemptions"]) - int(invite["redemptions"])),
        "allow_multiple_owners": invite["allow_multiple_owners"],
        "join": {
            "method": "POST",
            "url": "/api/auth/join",
            "fields": ["invite_id", "s", "display_name", "metadata"],
        },
        "metadata_known_keys": list(METADATA_KNOWN_KEYS),
        "candidate": {
            "present": bool(candidate.get("present")),
            "onboarded": onboarded,
        },
        "join_blocked": not onboarded,
        "onboarding": join_onboarding_section(settings, invite),
        "heartbeat_s": 10,
        "now": utc_now(),
    }
