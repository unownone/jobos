"""Operator home: hunt funnel, agent load, and pipeline age.

Read-only. Any authenticated principal on the tenant can load it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, RedirectResponse

from app.auth import Principal
from app.constants import (
    FUNNEL_APPLIED_STATUSES,
    FUNNEL_OUTREACHED_STATUSES,
    PIPELINE_OPEN_STATUSES,
    ROLE_TO_TRACK,
)
from app.db import BoardDB
from app.presence import (
    derive_status,
    list_presence_rows,
    parse_ts,
)
from app.profile import candidate_onboarded
from app.settings import Settings

STATIC_DIR = Path(__file__).resolve().parent / "static"
WORKING_STATUSES = frozenset({"working", "producing"})
AGENT_KINDS = frozenset({"agent", "owner"})


def utc_day_start(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")


def iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def days_between(raw: str | None, now: datetime) -> int | None:
    then = parse_ts(raw)
    if then is None:
        return None
    delta = now - then
    return max(0, int(delta.total_seconds() // 86400))


def _count_status(counts: dict[str, int], wanted: frozenset[str]) -> int:
    return sum(counts.get(status, 0) for status in wanted)


def _agent_user(db: BoardDB, user_id: str) -> dict[str, Any] | None:
    user = db.get_user(user_id)
    if user is not None:
        return user
    if not str(user_id).startswith("compat:"):
        return None
    parts = str(user_id).split(":", 2)
    role = parts[1] if len(parts) > 1 else ""
    track = ROLE_TO_TRACK.get(role)
    if not track:
        return None
    return {"id": user_id, "kind": "agent", "track": track}


def summarize_dashboard(db: BoardDB, tenant: Any, *, now: datetime | None = None) -> dict[str, Any]:
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    day_start = utc_day_start(clock)
    by_status = db.status_counts(tenant)
    found = sum(by_status.values())
    applied = _count_status(by_status, FUNNEL_APPLIED_STATUSES)
    outreached = _count_status(by_status, FUNNEL_OUTREACHED_STATUSES)

    found_today = db.count_jobs_created_since(tenant, day_start)
    applied_today = db.count_events_to_status_since(tenant, "applied", day_start)

    oldest_job = db.oldest_open_job(tenant, sorted(PIPELINE_OPEN_STATUSES))
    oldest: dict[str, Any] | None = None
    if oldest_job is not None:
        job = oldest_job
        posted = (job.get("posted_at") or "").strip()
        found_at = job.get("created_at") or ""
        age_from = posted or found_at
        oldest = {
            "id": job["id"],
            "company": job["company"],
            "title": job["title"],
            "status": job["status"],
            "location": job.get("location") or "",
            "pay": job.get("pay") or "",
            "posted_at": posted,
            "created_at": found_at,
            "days_in_pipeline": days_between(age_from, clock),
            "posted_known": bool(posted),
        }

    agents = db.list_users(tenant, kind="agent") + db.list_users(tenant, kind="owner")
    total_agents = len(agents)
    known_ids = {row["id"] for row in agents}
    working = 0
    live = 0
    for row in list_presence_rows(db, tenant):
        user = _agent_user(db, row["user_id"])
        if user is None:
            continue
        kind = user.get("kind")
        if kind not in AGENT_KINDS and row["user_id"] not in known_ids:
            continue
        if kind not in AGENT_KINDS and not str(row["user_id"]).startswith("compat:"):
            continue
        status = derive_status(
            last_heartbeat=parse_ts(row.get("last_heartbeat")),
            connected_at=parse_ts(row.get("connected_at")),
            status_hint=row.get("status_hint"),
            producing_flag=bool(row.get("producing")),
            has_claim=False,
            recent_write=False,
            now=clock,
        )
        if status in {"logged_in", "idle", "working", "producing"}:
            live += 1
        if status in WORKING_STATUSES:
            working += 1

    return {
        "as_of": iso_z(clock),
        "funnel": {
            "found": found,
            "applied": applied,
            "outreached": outreached,
        },
        "status_counts": by_status,
        "agents": {
            "total": total_agents,
            "working": working,
            "live": live,
        },
        "today": {
            "found": found_today,
            "applied": applied_today,
            "day_start": day_start,
        },
        "oldest_in_pipeline": oldest,
    }


def mount_dashboard(
    app: Any,
    db: BoardDB,
    principal_dep: Any,
    settings: Settings,
) -> None:
    router = APIRouter()

    @router.get("/home", response_model=None)
    def home_page(principal: Principal = Depends(principal_dep)) -> FileResponse | RedirectResponse:
        if db.admin_bootstrapped() and not candidate_onboarded(
            settings, db, tenant=principal.tenant
        ):
            return RedirectResponse(url="/onboarding", status_code=302)
        return FileResponse(STATIC_DIR / "home.html")

    @router.get("/api/dashboard")
    def dashboard(principal: Principal = Depends(principal_dep)) -> dict[str, Any]:
        return summarize_dashboard(db, principal.tenant)

    app.include_router(router)
