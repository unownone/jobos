"""Candidate public slice, resume, and mandatory onboarding writes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

from app.auth import Principal, require_admin
from app.permissions import ensure_can_resume
from app.profile import (
    EMPTY_TEMPLATE,
    candidate_status,
    dump_profile_yaml,
    hub_candidate_path,
    hub_resume_path,
    parse_candidate_body,
    public_candidate_for_settings,
    resolve_candidate_path,
    resolve_resume_path,
    validate_profile,
)
from app.settings import Settings


def create_candidate_router(settings: Settings, principal_dep: Any) -> APIRouter:
    router = APIRouter(tags=["candidate"])

    @router.get("/api/candidate/status")
    def candidate_status_endpoint() -> dict[str, Any]:
        return candidate_status(settings)

    @router.get("/api/candidate/template")
    def candidate_template(principal: Principal = Depends(principal_dep)) -> dict[str, Any]:
        require_admin(principal)
        return {"template": EMPTY_TEMPLATE, "example_rejected": True}

    @router.get("/api/candidate/public")
    def candidate_public(principal: Principal = Depends(principal_dep)) -> dict[str, Any]:
        del principal
        return public_candidate_for_settings(settings)

    @router.get("/api/candidate/resume")
    def candidate_resume(principal: Principal = Depends(principal_dep)) -> FileResponse:
        ensure_can_resume(principal.role)
        path = resolve_resume_path(settings)
        if path is None:
            raise HTTPException(status_code=404, detail="resume PDF not uploaded")
        return FileResponse(path, media_type="application/pdf", filename=path.name)

    @router.put("/api/candidate")
    async def candidate_put(
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        require_admin(principal)
        raw = await request.body()
        if not raw.strip():
            raise HTTPException(status_code=422, detail="empty candidate yaml")
        try:
            data = parse_candidate_body(raw, request.headers.get("content-type") or "")
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc) or "invalid candidate document") from exc
        missing = validate_profile(data)
        if missing:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "candidate profile is incomplete or is the example file",
                    "missing": missing,
                },
            )
        dest = hub_candidate_path(settings)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(dump_profile_yaml(data), encoding="utf-8")
        request.app.state.db.add_event(
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="candidate_put",
            note="stored gitignored hub candidate.yaml",
        )
        status = candidate_status(settings)
        return {"ok": True, "present": True, "path": "hub-data/profiles/candidate.yaml", **status}

    @router.put("/api/candidate/resume")
    async def candidate_resume_put(
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        require_admin(principal)
        dest = hub_resume_path(settings)
        dest.parent.mkdir(parents=True, exist_ok=True)
        raw = await request.body()
        if not raw:
            raise HTTPException(status_code=422, detail="empty resume")
        dest.write_bytes(raw)
        request.app.state.db.add_event(
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="resume_put",
            note="stored gitignored hub resume PDF",
        )
        return {"ok": True, "resume_url": "/api/candidate/resume", **candidate_status(settings)}

    @router.get("/api/candidate")
    def candidate_admin_get(principal: Principal = Depends(principal_dep)) -> PlainTextResponse:
        require_admin(principal)
        path = resolve_candidate_path(settings)
        if path is None:
            raise HTTPException(
                status_code=404,
                detail="profiles/candidate.yaml missing; open /onboarding — do not invent one",
            )
        return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/yaml")

    return router
