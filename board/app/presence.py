"""Heartbeat, live presence, and admin/owner directory. Phase C.

`POST /api/presence/heartbeat` is the only heartbeat route. Inbox
`pending_messages` is the unread count from the messages store (Phase G).
Never return API keys, hashes, or secrets in directory payloads.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from app.auth import Principal
from app.constants import ROLE_TO_TRACK, role_for_track
from app.db import BoardDB
from app.message_store import count_unread
from app.memory_store import row_to_item, safe_compact_recall
from app.profile import candidate_status
from app.tenant import TenantContext

STATIC_DIR = Path(__file__).resolve().parent / "static"

HEARTBEAT_S = 10
STALE_AFTER_S = 30
IDLE_AFTER_S = 60
PRODUCING_WRITE_S = 60
SESSION_GRACE_S = 60

PRESENCE_STATUSES = (
    "logged_in",
    "idle",
    "working",
    "producing",
    "stale",
)

STATUS_HINTS = frozenset(PRESENCE_STATUSES)

SECRET_NAME_FRAGMENTS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "cookie",
    "key_hash",
    "csrf",
)

Clock = Callable[[], datetime]


def parse_ts(raw: str | None) -> datetime | None:
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


def iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def age_seconds(then: datetime | None, now: datetime) -> float | None:
    if then is None:
        return None
    return (now - then).total_seconds()


def clock_from_request(request: Request) -> Clock:
    clock = getattr(request.app.state, "clock", None)
    if callable(clock):
        return clock
    return lambda: datetime.now(timezone.utc)


def active_claim_for_user(_db: BoardDB, _user_id: str, _now: datetime) -> dict[str, Any] | None:
    """Phase D hook: unacked queue claim with a valid lease. None until the queue ships."""
    return None


def _looks_secret_key(name: str) -> bool:
    lowered = name.lower().replace("-", "_")
    return any(fragment in lowered for fragment in SECRET_NAME_FRAGMENTS)


def safe_metadata(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if _looks_secret_key(str(key)):
            continue
        if isinstance(value, dict):
            nested = safe_metadata(value)
            if nested:
                out[str(key)] = nested
            continue
        if isinstance(value, str) and _looks_secret_value(value):
            continue
        out[str(key)] = value
    return out


def _looks_secret_value(value: str) -> bool:
    text = value.strip()
    if text.startswith(("jh_agt_", "jh_own_", "jh_inv_", "jh_boot_", "jh_adm_")):
        return True
    return False


def directory_kind(stored_kind: str | None, *, compat: bool = False) -> str:
    if compat or stored_kind == "compat":
        return "compat"
    if stored_kind in {"admin", "viewer"}:
        return "human"
    if stored_kind in {"owner", "agent", "human"}:
        return stored_kind
    return stored_kind or "human"


def derive_status(
    *,
    last_heartbeat: datetime | None,
    connected_at: datetime | None,
    status_hint: str | None,
    producing_flag: bool,
    has_claim: bool,
    recent_write: bool,
    now: datetime,
    stale_after_s: float = STALE_AFTER_S,
    idle_after_s: float = IDLE_AFTER_S,
) -> str:
    if last_heartbeat is None:
        return "stale"
    if (age_seconds(last_heartbeat, now) or 0) > stale_after_s:
        return "stale"
    hint = (status_hint or "").strip().lower()
    working = has_claim or hint in {"working", "producing"}
    producing = working and (producing_flag or hint == "producing" or recent_write)
    if producing:
        return "producing"
    if working:
        return "working"
    connected = connected_at or last_heartbeat
    if (age_seconds(connected, now) or 0) > idle_after_s:
        return "idle"
    return "logged_in"


def current_task_payload(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    task_id = row.get("task_id") or None
    if not task_id:
        return None
    return {
        "id": task_id,
        "kind": row.get("task_kind") or None,
        "job_id": row.get("job_id") or None,
    }


def public_presence(
    *,
    user_id: str,
    user: dict[str, Any] | None,
    row: dict[str, Any] | None,
    status: str,
    last_seen: str | None,
    compat_actor: str | None = None,
    compat_role: str | None = None,
) -> dict[str, Any]:
    meta = safe_metadata((user or {}).get("metadata") or {})
    stored_kind = (user or {}).get("kind")
    track = (user or {}).get("track")
    if user is None and compat_role:
        track = ROLE_TO_TRACK.get(compat_role)
    role = "admin" if stored_kind == "admin" else (role_for_track(track) or compat_role or "")
    if stored_kind == "viewer":
        role = "maintenance"
    payload = {
        "user_id": user_id,
        "display_name": (user or {}).get("display_name") or compat_actor or user_id,
        "track": track,
        "kind": directory_kind(stored_kind, compat=user is None and bool(compat_role)),
        "role": role,
        "model": meta.get("model"),
        "harness": meta.get("harness"),
        "bed": meta.get("bed"),
        "last_seen": last_seen,
        "status": status,
        "current_task": current_task_payload(row),
    }
    return payload


def assert_no_secrets(payload: Any) -> None:
    blob = str(payload).lower()
    if "jh_agt_" in blob or "jh_own_" in blob or "jh_inv_" in blob:
        raise RuntimeError("presence payload leaked an API key prefix")
    if "password_hash" in blob or "key_hash" in blob:
        raise RuntimeError("presence payload leaked a hash field")


def _compat_user_id(principal: Principal) -> str:
    actor = (principal.actor or "anonymous").strip() or "anonymous"
    return f"compat:{principal.role}:{actor}"


def _require_presence_identity(principal: Principal) -> str:
    if principal.user_id:
        return principal.user_id
    if principal.auth == "compat_role":
        return _compat_user_id(principal)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="hub identity required (Bearer key or session)",
    )


PRESENCE_DDL = """
CREATE TABLE IF NOT EXISTS presence (
    user_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    status TEXT,
    status_hint TEXT,
    last_heartbeat TEXT NOT NULL,
    connected_at TEXT NOT NULL,
    task_id TEXT,
    task_kind TEXT,
    job_id TEXT,
    producing INTEGER NOT NULL DEFAULT 0,
    producing_at TEXT,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_presence_last_heartbeat ON presence(last_heartbeat);
"""


def ensure_presence_schema(db: BoardDB) -> None:
    db.conn.executescript(PRESENCE_DDL)
    db.conn.commit()


def _presence_from_row(row: Any) -> dict[str, Any]:
    return {
        "user_id": row["user_id"],
        "status": row["status"] or "",
        "status_hint": row["status_hint"] or "",
        "last_heartbeat": row["last_heartbeat"],
        "connected_at": row["connected_at"],
        "task_id": row["task_id"] or None,
        "task_kind": row["task_kind"] or None,
        "job_id": row["job_id"] or None,
        "producing": bool(row["producing"]),
        "producing_at": row["producing_at"] or None,
        "user_agent": row["user_agent"] or "",
    }


def get_presence_row(db: BoardDB, user_id: str) -> dict[str, Any] | None:
    cur = db.conn.execute("SELECT * FROM presence WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return _presence_from_row(row) if row else None


def list_presence_rows(db: BoardDB, tenant: TenantContext) -> list[dict[str, Any]]:
    cur = db.conn.execute(
        "SELECT * FROM presence WHERE account_id = ? ORDER BY last_heartbeat DESC",
        (tenant.account_id,),
    )
    return [_presence_from_row(r) for r in cur.fetchall()]


def upsert_presence_row(
    db: BoardDB,
    *,
    user_id: str,
    status: str,
    status_hint: str | None,
    last_heartbeat: str,
    connected_at: str,
    task_id: str | None,
    task_kind: str | None,
    job_id: str | None,
    producing: bool,
    producing_at: str | None,
    user_agent: str | None,
    tenant: TenantContext,
) -> dict[str, Any]:
    db.conn.execute(
        """
        INSERT INTO presence (
            user_id, account_id, status, status_hint, last_heartbeat, connected_at,
            task_id, task_kind, job_id, producing, producing_at, user_agent
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            account_id = excluded.account_id,
            status = excluded.status,
            status_hint = excluded.status_hint,
            last_heartbeat = excluded.last_heartbeat,
            connected_at = excluded.connected_at,
            task_id = excluded.task_id,
            task_kind = excluded.task_kind,
            job_id = excluded.job_id,
            producing = excluded.producing,
            producing_at = excluded.producing_at,
            user_agent = excluded.user_agent
        """,
        (
            user_id,
            tenant.account_id,
            status,
            status_hint,
            last_heartbeat,
            connected_at,
            task_id,
            task_kind,
            job_id,
            1 if producing else 0,
            producing_at,
            user_agent or "",
        ),
    )
    db.conn.commit()
    stored = get_presence_row(db, user_id)
    if stored is None:
        raise RuntimeError("presence upsert did not persist")
    return stored


def list_recent_sessions(db: BoardDB, since: str, tenant: TenantContext) -> list[dict[str, Any]]:
    cur = db.conn.execute(
        """
        SELECT s.id, s.user_id, s.last_seen, s.expires_at
        FROM sessions s
        WHERE s.last_seen >= ? AND s.account_id = ?
        ORDER BY s.last_seen DESC
        """,
        (since, tenant.account_id),
    )
    return [
        {
            "id": row["id"],
            "user_id": row["user_id"],
            "last_seen": row["last_seen"],
            "expires_at": row["expires_at"],
        }
        for row in cur.fetchall()
    ]


def user_activity(
    db: BoardDB,
    *,
    tenant: TenantContext,
    user_id: str,
    user: dict[str, Any] | None,
    compat_actor: str | None = None,
    limit: int = 24,
) -> dict[str, Any]:
    actors: list[str] = []
    for value in (user_id, (user or {}).get("display_name"), (user or {}).get("email"), compat_actor):
        text = str(value or "").strip()
        if text and text not in actors:
            actors.append(text)
    if not actors:
        return {"events": [], "memories": [], "tools": []}
    placeholders = ",".join("?" for _ in actors)
    event_cur = db.conn.execute(
        f"""
        SELECT * FROM events
        WHERE account_id = ? AND actor IN ({placeholders})
        ORDER BY id DESC LIMIT ?
        """,
        [tenant.account_id, *actors, limit],
    )
    events = []
    for row in event_cur.fetchall():
        events.append(
            {
                "id": row["id"],
                "ts": row["ts"],
                "job_id": row["job_id"],
                "actor_role": row["actor_role"],
                "actor": row["actor"] or "",
                "action": row["action"],
                "note": row["note"] or "",
            }
        )
    mem_cur = db.conn.execute(
        f"""
        SELECT * FROM memory_items
        WHERE account_id = ? AND created_by IN ({placeholders})
        ORDER BY updated_at DESC LIMIT ?
        """,
        [tenant.account_id, *actors, limit],
    )
    memories = [row_to_item(row, compact=True) for row in mem_cur.fetchall()]
    tool_cur = db.conn.execute(
        f"""
        SELECT tool_name, skill, COUNT(*) AS n, COALESCE(SUM(total_tokens), 0) AS tokens
        FROM token_burn
        WHERE account_id = ?
          AND (actor IN ({placeholders}) OR actor_role IN ({placeholders}))
        GROUP BY tool_name, skill
        ORDER BY tokens DESC, n DESC
        LIMIT ?
        """,
        [tenant.account_id, *actors, *actors, 20],
    )
    tools = [
        {
            "tool_name": row["tool_name"],
            "skill": row["skill"] or "",
            "n": int(row["n"] or 0),
            "tokens": int(row["tokens"] or 0),
        }
        for row in tool_cur.fetchall()
    ]
    return {"events": events, "memories": memories, "tools": tools}


def user_has_event_since(
    db: BoardDB, user: dict[str, Any], since: str, tenant: TenantContext
) -> bool:
    actors = [
        a
        for a in (user.get("id"), user.get("display_name"), user.get("email"))
        if a
    ]
    if not actors:
        return False
    placeholders = ",".join("?" * len(actors))
    cur = db.conn.execute(
        f"""SELECT 1 FROM events
            WHERE account_id = ?
              AND ts >= ?
              AND actor IN ({placeholders})
              AND job_id IS NOT NULL
              AND TRIM(job_id) != ''
            LIMIT 1""",
        [tenant.account_id, since, *actors],
    )
    return cur.fetchone() is not None


def _can_read_full_directory(principal: Principal) -> bool:
    if principal.kind == "admin" or principal.role == "admin":
        return True
    if principal.kind == "viewer" or principal.role == "maintenance":
        return True
    return False


def _ensure_can_read_presence(principal: Principal) -> None:
    if _can_read_full_directory(principal):
        return
    if principal.kind == "owner":
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="admin, maintenance, or a track owner can read presence",
    )


class HeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status_hint: str | None = None
    task_id: str | None = None
    producing: bool = False
    task_kind: str | None = None
    job_id: str | None = None


def create_presence_router(db: BoardDB, principal_dep: Any) -> APIRouter:
    ensure_presence_schema(db)
    router = APIRouter()

    def _row_status(
        row: dict[str, Any],
        user: dict[str, Any] | None,
        now: datetime,
        tenant: TenantContext,
    ) -> str:
        last_hb = parse_ts(row.get("last_heartbeat"))
        connected = parse_ts(row.get("connected_at"))
        claim = None
        if user and user.get("id"):
            claim = active_claim_for_user(db, user["id"], now)
        write_since = iso_z(now - timedelta(seconds=PRODUCING_WRITE_S))
        recent_write = bool(user) and user_has_event_since(db, user, write_since, tenant)
        return derive_status(
            last_heartbeat=last_hb,
            connected_at=connected,
            status_hint=row.get("status_hint"),
            producing_flag=bool(row.get("producing")),
            has_claim=bool(claim),
            recent_write=recent_write,
            now=now,
        )

    def _directory_rows(principal: Principal, now: datetime) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for row in list_presence_rows(db, principal.tenant):
            user = db.get_user(row["user_id"])
            computed = _row_status(row, user, now, principal.tenant)
            last_seen = row.get("last_heartbeat")
            compat_role = None
            compat_actor = None
            if user is None and str(row["user_id"]).startswith("compat:"):
                parts = str(row["user_id"]).split(":", 2)
                compat_role = parts[1] if len(parts) > 1 else None
                compat_actor = parts[2] if len(parts) > 2 else None
            item = public_presence(
                user_id=row["user_id"],
                user=user,
                row=row,
                status=computed,
                last_seen=last_seen,
                compat_actor=compat_actor,
                compat_role=compat_role,
            )
            seen.add(row["user_id"])
            out.append(item)

        grace_since = iso_z(now - timedelta(seconds=SESSION_GRACE_S))
        for sess in list_recent_sessions(db, grace_since, principal.tenant):
            uid = sess["user_id"]
            if uid in seen:
                continue
            user = db.get_user(uid)
            if user is None or user.get("disabled_at"):
                continue
            if user.get("kind") not in {"admin", "viewer"}:
                continue
            item = public_presence(
                user_id=uid,
                user=user,
                row=None,
                status="logged_in",
                last_seen=sess.get("last_seen"),
            )
            seen.add(uid)
            out.append(item)

        if _can_read_full_directory(principal):
            filtered = out
        else:
            filtered = [row for row in out if row.get("track") == principal.track]

        for item in filtered:
            assert_no_secrets(item)
        return filtered

    @router.post("/api/presence/heartbeat")
    def heartbeat(
        request: Request,
        body: HeartbeatIn = HeartbeatIn(),
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        payload = body
        hint = (payload.status_hint or "").strip().lower() or None
        if hint and hint not in STATUS_HINTS:
            raise HTTPException(
                status_code=422,
                detail=f"status_hint must be one of {list(PRESENCE_STATUSES)}",
            )
        user_id = _require_presence_identity(principal)
        now = clock_from_request(request)()
        now_iso = iso_z(now)
        existing = get_presence_row(db, user_id)
        last_hb = parse_ts(existing.get("last_heartbeat") if existing else None)
        stale_already = (
            existing is None
            or last_hb is None
            or (age_seconds(last_hb, now) or 0) > STALE_AFTER_S
        )
        connected_at = now_iso if stale_already else existing["connected_at"]
        producing_at = existing.get("producing_at") if existing else None
        if payload.producing or hint == "producing":
            producing_at = now_iso
        user = db.get_user(user_id) if principal.user_id else None
        claim = active_claim_for_user(db, user_id, now) if principal.user_id else None
        write_since = iso_z(now - timedelta(seconds=PRODUCING_WRITE_S))
        recent_write = bool(user) and user_has_event_since(
            db, user, write_since, principal.tenant
        )
        computed = derive_status(
            last_heartbeat=now,
            connected_at=parse_ts(connected_at),
            status_hint=hint,
            producing_flag=bool(payload.producing),
            has_claim=bool(claim),
            recent_write=recent_write,
            now=now,
        )
        stored = upsert_presence_row(
            db,
            user_id=user_id,
            status=computed,
            status_hint=hint,
            last_heartbeat=now_iso,
            connected_at=connected_at,
            task_id=(payload.task_id or "").strip() or None,
            task_kind=(payload.task_kind or "").strip() or None,
            job_id=(payload.job_id or "").strip() or None,
            producing=bool(payload.producing) or hint == "producing",
            producing_at=producing_at,
            user_agent=request.headers.get("user-agent"),
            tenant=principal.tenant,
        )
        self_row = public_presence(
            user_id=user_id,
            user=user,
            row=stored,
            status=computed,
            last_seen=now_iso,
            compat_actor=principal.actor if user is None else None,
            compat_role=principal.role if user is None else None,
        )
        assert_no_secrets(self_row)
        memory = safe_compact_recall(
            db,
            principal,
            job_id=(payload.job_id or "").strip() or None,
        )
        settings = request.app.state.settings
        cand = candidate_status(settings)
        return {
            "ok": True,
            "status": computed,
            "heartbeat_s": HEARTBEAT_S,
            "stale_after_s": STALE_AFTER_S,
            "last_seen": now_iso,
            "pending_messages": count_unread(db, principal),
            "memory": memory,
            "candidate_revision": cand.get("revision"),
            "candidate_onboarded": cand.get("onboarded"),
            "self": self_row,
        }

    @router.get("/api/presence")
    def list_presence(
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        _ensure_can_read_presence(principal)
        now = clock_from_request(request)()
        users = _directory_rows(principal, now)
        return {
            "users": users,
            "heartbeat_s": HEARTBEAT_S,
            "stale_after_s": STALE_AFTER_S,
            "now": iso_z(now),
            "role": principal.role,
        }

    @router.get("/api/presence/{user_id}")
    def presence_detail(
        user_id: str,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        _ensure_can_read_presence(principal)
        now = clock_from_request(request)()
        row = get_presence_row(db, user_id)
        user = db.get_user(user_id)
        compat_role = None
        compat_actor = None
        if user is None and user_id.startswith("compat:"):
            parts = user_id.split(":", 2)
            compat_role = parts[1] if len(parts) > 1 else None
            compat_actor = parts[2] if len(parts) > 2 else None
        if row is None and user is None and compat_actor is None:
            raise HTTPException(status_code=404, detail="presence not found")
        computed = _row_status(row or {}, user, now, principal.tenant) if row else "offline"
        item = public_presence(
            user_id=user_id,
            user=user,
            row=row,
            status=computed,
            last_seen=(row or {}).get("last_heartbeat"),
            compat_actor=compat_actor,
            compat_role=compat_role,
        )
        activity = user_activity(
            db,
            tenant=principal.tenant,
            user_id=user_id,
            user=user,
            compat_actor=compat_actor,
        )
        job = None
        job_id = item.get("current_task") and item["current_task"].get("id")
        if not job_id and row:
            job_id = row.get("job_id")
        if job_id:
            job = db.get_job(principal.tenant, str(job_id))
            if job:
                job = {
                    "id": job["id"],
                    "company": job["company"],
                    "title": job["title"],
                    "status": job["status"],
                }
        payload = {
            "user": item,
            "job": job,
            "events": activity["events"],
            "memories": activity["memories"],
            "tools": activity["tools"],
            "now": iso_z(now),
        }
        assert_no_secrets(payload)
        return payload

    @router.get("/api/users")
    def list_users_directory(
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        if principal.kind != "admin" and principal.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
        now = clock_from_request(request)()
        presence_by_id = {row["user_id"]: row for row in list_presence_rows(db, principal.tenant)}
        users: list[dict[str, Any]] = []
        for user in db.list_users(principal.tenant, include_disabled=True):
            row = presence_by_id.get(user["id"])
            if row:
                computed = _row_status(row, user, now, principal.tenant)
                last_seen = row.get("last_heartbeat")
            else:
                computed = None
                last_seen = None
            item = public_presence(
                user_id=user["id"],
                user=user,
                row=row,
                status=computed or "offline",
                last_seen=last_seen,
            )
            item["disabled_at"] = user.get("disabled_at")
            item["email"] = user.get("email")
            item["created_at"] = user.get("created_at")
            assert_no_secrets(item)
            users.append(item)
        return {
            "users": users,
            "heartbeat_s": HEARTBEAT_S,
            "stale_after_s": STALE_AFTER_S,
            "now": iso_z(now),
        }

    @router.get("/admin/users")
    def users_page(principal: Principal = Depends(principal_dep)) -> FileResponse:
        del principal
        return FileResponse(STATIC_DIR / "users.html")

    return router


PRESENCE_PATHS = frozenset(
    {
        "/api/presence/heartbeat",
        "/api/presence",
        "/api/presence/{user_id}",
        "/api/users",
        "/admin/users",
    }
)


def mount_presence(app: Any, db: BoardDB, principal_dep: Any) -> None:
    """Register Phase C routes last and replace any sibling stub on the same paths."""
    ensure_presence_schema(db)
    app.router.routes = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) not in PRESENCE_PATHS
    ]
    app.include_router(create_presence_router(db, principal_dep))
