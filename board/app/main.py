"""FastAPI hunt board. Maintainer-owned. Bind 0.0.0.0 so sibling agents can reach it."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app.auth import Principal, require_principal
from app.constants import ROLES, STATUSES
from app.db import BoardDB
from app.metrics import MetricsStore
from app.permissions import (
    authorize_create,
    authorize_patch,
    capabilities,
    ensure_can_delete,
    ensure_can_hygiene,
    ensure_can_import,
    ensure_can_read_metrics,
    ensure_can_stop,
    validate_status,
)
from app.settings import Settings, load_settings

STATIC_DIR = Path(__file__).resolve().parent / "static"
ID_RE = re.compile(r"^[a-z0-9]+__[a-zA-Z0-9._-]+$")
SLUG_RE = re.compile(r"[^a-z0-9]+")


class JobIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    company: str
    title: str
    location: str | None = None
    remote: str | bool | None = None
    url: str | None = None
    apply_url: str | None = None
    apply_kind: str | None = None
    ats: str | None = None
    req_id: str | None = None
    sources: list[str] | None = None
    status: str | None = "discovered"
    score: float | None = None
    owners: dict[str, str] | None = None
    apply_packet: dict[str, Any] | None = None
    outreach_packet: dict[str, Any] | None = None
    research: dict[str, Any] | None = None
    proof: dict[str, Any] | None = None
    notes: str | None = None
    conflicts: list[Any] | None = None
    stopped: bool | None = None
    stop_reason: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class JobPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str | None = None
    title: str | None = None
    location: str | None = None
    remote: str | bool | None = None
    url: str | None = None
    apply_url: str | None = None
    apply_kind: str | None = None
    ats: str | None = None
    req_id: str | None = None
    sources: list[str] | None = None
    status: str | None = None
    score: float | None = None
    owners: dict[str, str] | None = None
    apply_packet: dict[str, Any] | None = None
    outreach_packet: dict[str, Any] | None = None
    research: dict[str, Any] | None = None
    proof: dict[str, Any] | None = None
    notes: str | None = None
    conflicts: list[Any] | None = None
    stopped: bool | None = None
    stop_reason: str | None = None


class StopIn(BaseModel):
    reason: str = Field(min_length=1)


class PauseIn(BaseModel):
    reason: str = Field(min_length=1)


class TokenBurnIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    tool_name: str = Field(min_length=1)
    skill: str | None = None
    lane: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int | None = None
    cost_usd: float | None = None
    duration_ms: float | None = None
    job_id: str | None = None
    timestamp: str | None = None
    extra: dict[str, Any] | None = None


class ImportIn(BaseModel):
    jobs: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    replace: bool = False


def _slug_id(company: str, title: str) -> str:
    slug = SLUG_RE.sub("-", f"{company}-{title}".lower()).strip("-")[:72]
    return f"board__{slug or 'job'}"


def _normalize_id(raw: str) -> str:
    job_id = raw.strip()
    if not ID_RE.match(job_id):
        raise HTTPException(
            status_code=422,
            detail="id must match {source}__{stable_id} (ledger schema)",
        )
    return job_id


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    db = BoardDB(settings.db_path)
    metrics = MetricsStore(
        settings.db_path.parent / "metrics.sqlite",
        settings.db_path.parent / "metrics.jsonl",
    )
    principal_dep = require_principal(settings)

    app = FastAPI(
        title="Get That Job hunt board",
        description="Private live coordination plane. Maintainer owns tokens, schema, and uptime.",
        version="0.1.0",
    )
    app.state.settings = settings
    app.state.db = db
    app.state.metrics = metrics

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/favicon.ico")
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/health")
    def health() -> dict[str, Any]:
        configured = sorted(role for role, token in settings.tokens.items() if token)
        return {
            "ok": True,
            "roles_configured": configured,
            "all_roles_configured": configured == sorted(ROLES),
        }

    @app.get("/api/meta")
    def meta(principal: Principal = Depends(principal_dep)) -> dict[str, Any]:
        return {
            "statuses": list(STATUSES),
            "roles": list(ROLES),
            "capabilities": capabilities(principal.role),
            "owner": "maintainer",
        }

    @app.get("/api/whoami")
    def whoami(principal: Principal = Depends(principal_dep)) -> dict[str, Any]:
        return {
            "role": principal.role,
            "actor": principal.actor,
            **capabilities(principal.role),
        }

    @app.get("/api/jobs")
    def list_jobs(
        principal: Principal = Depends(principal_dep),
        status_filter: Annotated[str | None, Query(alias="status")] = None,
        q: str | None = None,
        stopped: bool | None = None,
    ) -> dict[str, Any]:
        if status_filter:
            validate_status(status_filter)
        jobs = db.list_jobs(status=status_filter, q=q, stopped=stopped)
        total = len(db.list_jobs())
        return {
            "jobs": jobs,
            "count": len(jobs),
            "total": total,
            "role": principal.role,
        }

    @app.get("/api/jobs/{job_id}")
    def get_job(
        job_id: str,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        job = db.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return {"job": job, "role": principal.role}

    @app.post("/api/jobs", status_code=201)
    def create_job(
        body: JobIn,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        raw = body.model_dump(exclude_none=True)
        payload = authorize_create(principal.role, {k: v for k, v in raw.items() if v != ""})
        job_id = _normalize_id(payload["id"]) if payload.get("id") else _slug_id(
            payload["company"], payload["title"]
        )
        if db.get_job(job_id):
            raise HTTPException(status_code=409, detail=f"job id already exists: {job_id}")
        dup = db.find_duplicate(
            apply_url=str(payload.get("apply_url") or ""),
            company=payload["company"],
            title=payload["title"],
            location=str(payload.get("location") or ""),
        )
        if dup:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "duplicate job",
                    "existing_id": dup["id"],
                    "matched": "apply_url or company+title+location",
                },
            )
        payload["id"] = job_id
        payload["created_by_role"] = principal.role
        stored = db.insert_job(payload)
        event = db.add_event(
            job_id=job_id,
            actor_role=principal.role,
            actor=principal.actor,
            action="create",
            from_status=None,
            to_status=stored["status"],
            note="created",
            fields={"company": stored["company"], "title": stored["title"]},
        )
        return {"job": stored, "event": event}

    @app.patch("/api/jobs/{job_id}")
    def patch_job(
        job_id: str,
        body: JobPatch,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        current = db.get_job(job_id)
        if current is None:
            raise HTTPException(status_code=404, detail="job not found")
        incoming = body.model_dump(exclude_none=True)
        if not incoming:
            return {"job": current, "event": None}
        patch = authorize_patch(principal.role, current, incoming)
        stored = db.update_job(job_id, patch)
        event = db.add_event(
            job_id=job_id,
            actor_role=principal.role,
            actor=principal.actor,
            action="patch",
            from_status=current["status"],
            to_status=stored["status"],
            note="patched " + ", ".join(sorted(patch)),
            fields=patch,
        )
        return {"job": stored, "event": event}

    @app.post("/api/jobs/{job_id}/stop")
    def stop_job(
        job_id: str,
        body: StopIn,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_stop(principal.role)
        current = db.get_job(job_id)
        if current is None:
            raise HTTPException(status_code=404, detail="job not found")
        stored = db.update_job(
            job_id,
            {
                "stopped": True,
                "stop_reason": body.reason,
                "status": "closed_withdrawn",
            },
        )
        event = db.add_event(
            job_id=job_id,
            actor_role=principal.role,
            actor=principal.actor,
            action="stop",
            from_status=current["status"],
            to_status=stored["status"],
            note=body.reason,
        )
        return {"job": stored, "event": event}

    @app.post("/api/jobs/{job_id}/pause")
    def pause_job(
        job_id: str,
        body: PauseIn,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_stop(principal.role)
        current = db.get_job(job_id)
        if current is None:
            raise HTTPException(status_code=404, detail="job not found")
        stored = db.update_job(
            job_id,
            {
                "stopped": True,
                "stop_reason": body.reason,
            },
        )
        event = db.add_event(
            job_id=job_id,
            actor_role=principal.role,
            actor=principal.actor,
            action="pause",
            from_status=current["status"],
            to_status=stored["status"],
            note=body.reason,
        )
        return {"job": stored, "event": event}

    @app.post("/api/jobs/{job_id}/resume")
    def resume_job(
        job_id: str,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_stop(principal.role)
        current = db.get_job(job_id)
        if current is None:
            raise HTTPException(status_code=404, detail="job not found")
        stored = db.update_job(
            job_id,
            {
                "stopped": False,
                "stop_reason": "",
            },
        )
        event = db.add_event(
            job_id=job_id,
            actor_role=principal.role,
            actor=principal.actor,
            action="resume",
            from_status=current["status"],
            to_status=stored["status"],
            note="resumed",
        )
        return {"job": stored, "event": event}

    @app.delete("/api/jobs/{job_id}")
    def delete_job(
        job_id: str,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_delete(principal.role)
        current = db.get_job(job_id)
        if current is None:
            raise HTTPException(status_code=404, detail="job not found")
        db.delete_job(job_id)
        event = db.add_event(
            job_id=job_id,
            actor_role=principal.role,
            actor=principal.actor,
            action="delete",
            from_status=current["status"],
            to_status=None,
            note="deleted",
        )
        return {"ok": True, "id": job_id, "event": event}

    @app.get("/api/events")
    def list_events(
        principal: Principal = Depends(principal_dep),
        job_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return {"events": db.list_events(job_id=job_id, limit=limit), "role": principal.role}

    @app.get("/api/hygiene")
    def hygiene_report(
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_hygiene(principal.role)
        jobs = db.list_jobs()
        by_url: dict[str, list[str]] = {}
        by_ctl: dict[tuple[str, str, str], list[str]] = {}
        stale: list[str] = []
        missing_packet: list[str] = []
        for job in jobs:
            url = (job.get("apply_url") or "").strip()
            if url:
                by_url.setdefault(url, []).append(job["id"])
            key = (
                (job.get("company") or "").lower(),
                (job.get("title") or "").lower(),
                (job.get("location") or "").lower(),
            )
            by_ctl.setdefault(key, []).append(job["id"])
            if job["status"] in {"applying", "outreaching"}:
                stale.append(job["id"])
            packet = job.get("apply_packet") or {}
            if job["status"] == "apply_ready" and not packet.get("url") and not packet.get("steps"):
                missing_packet.append(job["id"])
        return {
            "counts_by_status": db.counts_by_status(),
            "duplicate_apply_urls": [
                {"apply_url": url, "ids": ids} for url, ids in by_url.items() if len(ids) > 1
            ],
            "duplicate_company_title_location": [
                {"company": k[0], "title": k[1], "location": k[2], "ids": ids}
                for k, ids in by_ctl.items()
                if len(ids) > 1
            ],
            "active_claims": stale,
            "apply_ready_missing_packet": missing_packet,
            "stopped": [j["id"] for j in jobs if j.get("stopped")],
        }

    @app.post("/api/hygiene/vacuum")
    def hygiene_vacuum(
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_hygiene(principal.role)
        db.vacuum()
        db.add_event(
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="vacuum",
            note="sqlite vacuum",
        )
        return {"ok": True}

    @app.post("/api/import")
    def import_history(
        body: ImportIn,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_import(principal.role)
        if body.replace and principal.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="only admin can replace the board during import",
            )
        if body.replace:
            for job in db.list_jobs():
                db.delete_job(job["id"])
        created = 0
        updated = 0
        skipped = 0
        for raw in body.jobs:
            if not isinstance(raw, dict) or not raw.get("company") or not raw.get("title"):
                skipped += 1
                continue
            job_id = str(raw.get("id") or _slug_id(str(raw["company"]), str(raw["title"])))
            if not ID_RE.match(job_id):
                skipped += 1
                continue
            existing = db.get_job(job_id)
            row = {
                "id": job_id,
                "company": raw["company"],
                "title": raw["title"],
                "location": raw.get("location") or "",
                "remote": raw.get("remote"),
                "url": raw.get("url") or "",
                "apply_url": raw.get("apply_url") or "",
                "apply_kind": raw.get("apply_kind") or "",
                "ats": raw.get("ats") or "",
                "req_id": str(raw.get("req_id") or ""),
                "sources": raw.get("sources") or [],
                "status": raw.get("status") or "discovered",
                "score": raw.get("score"),
                "owners": raw.get("owners") or {},
                "apply_packet": raw.get("apply_packet") or {},
                "outreach_packet": raw.get("outreach_packet") or {},
                "research": raw.get("research") or {},
                "proof": raw.get("proof") or {},
                "notes": raw.get("notes") or "",
                "conflicts": raw.get("conflicts") or [],
                "stopped": bool(raw.get("stopped")),
                "stop_reason": raw.get("stop_reason") or "",
                "created_at": raw.get("created_at"),
                "updated_at": raw.get("updated_at"),
                "created_by_role": principal.role,
            }
            try:
                validate_status(str(row["status"]))
            except HTTPException:
                skipped += 1
                continue
            if existing:
                db.update_job(job_id, {k: v for k, v in row.items() if k != "id"})
                updated += 1
            else:
                db.insert_job(row)
                created += 1
        for raw_event in body.events:
            if not isinstance(raw_event, dict):
                continue
            db.add_event(
                job_id=raw_event.get("job_id"),
                actor_role=str(raw_event.get("role") or raw_event.get("actor_role") or principal.role),
                actor=str(raw_event.get("actor") or ""),
                action=str(raw_event.get("action") or "import"),
                from_status=raw_event.get("from"),
                to_status=raw_event.get("to"),
                note=str(raw_event.get("note") or "imported"),
            )
        db.add_event(
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="import",
            note=f"created={created} updated={updated} skipped={skipped}",
        )
        return {"created": created, "updated": updated, "skipped": skipped}

    @app.post("/api/metrics/token_burn", status_code=201)
    def log_token_burn(
        body: TokenBurnIn,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        payload = body.model_dump(exclude_none=True)
        extra = payload.pop("extra", None) or {}
        for key in list(payload.keys()):
            if key not in {
                "tool_name",
                "skill",
                "lane",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "cost_usd",
                "duration_ms",
                "job_id",
                "timestamp",
            }:
                extra[key] = payload.pop(key)
        payload["extra"] = extra
        payload["actor_role"] = principal.role
        payload["actor"] = principal.actor
        stored = metrics.record_token_burn(payload)
        return {"ok": True, "row": stored}

    @app.get("/api/metrics/token_burn")
    def list_token_burn(
        principal: Principal = Depends(principal_dep),
        limit: int = 100,
    ) -> dict[str, Any]:
        ensure_can_read_metrics(principal.role)
        return {"rows": metrics.list_burns(limit=limit)}

    @app.get("/api/metrics/summary")
    def metrics_summary(
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_read_metrics(principal.role)
        return metrics.summary()

    @app.exception_handler(HTTPException)
    async def http_exc(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return app
