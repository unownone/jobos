"""Candidate public slice, resume, and mandatory onboarding writes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from app.auth import Principal, require_admin
from app.permissions import ensure_can_resume
from app.profile import (
    EMPTY_TEMPLATE,
    candidate_blob_text,
    candidate_status,
    dump_profile_yaml,
    parse_candidate_body,
    public_candidate_for_settings,
    resolve_candidate_path,
    resume_blob_bytes,
    resolve_resume_path,
    validate_profile,
    write_candidate_yaml,
    write_resume_pdf,
)
from app.settings import Settings

NO_STORE = {"Cache-Control": "no-store"}


def _fresh_json(payload: dict[str, Any]) -> JSONResponse:
    revision = payload.get("revision")
    headers = dict(NO_STORE)
    if revision:
        headers["ETag"] = f'"{revision}"'
    return JSONResponse(payload, headers=headers)


def create_candidate_router(settings: Settings, principal_dep: Any) -> APIRouter:
    router = APIRouter(tags=["candidate"])

    @router.get("/api/candidate/status")
    def candidate_status_endpoint(principal: Principal = Depends(principal_dep)) -> JSONResponse:
        del principal
        payload = candidate_status(settings)
        return _fresh_json(payload)

    @router.get("/api/candidate/template")
    def candidate_template(principal: Principal = Depends(principal_dep)) -> dict[str, Any]:
        require_admin(principal)
        return {"template": EMPTY_TEMPLATE, "example_rejected": True}

    @router.get("/api/candidate/public")
    def candidate_public(principal: Principal = Depends(principal_dep)) -> JSONResponse:
        del principal
        payload = public_candidate_for_settings(settings)
        return _fresh_json(payload)

    @router.get("/api/candidate/resume")
    def candidate_resume(principal: Principal = Depends(principal_dep)) -> Response:
        ensure_can_resume(principal.role)
        raw = resume_blob_bytes()
        filename = "candidate-resume.pdf"
        if raw is None:
            path = resolve_resume_path(settings)
            if path is None:
                raise HTTPException(status_code=404, detail="resume PDF not uploaded")
            raw = path.read_bytes()
            filename = path.name
        return Response(
            content=raw,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    @router.put("/api/candidate")
    async def candidate_put(
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> JSONResponse:
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
        write_candidate_yaml(settings, dump_profile_yaml(data), db=request.app.state.db)
        request.app.state.db.add_event(
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="candidate_put",
            note="stored candidate.yaml in postgres hub_blobs",
        )
        status = candidate_status(settings, db=request.app.state.db)
        return _fresh_json({"ok": True, "present": True, "path": "postgres:hub_blobs/candidate.yaml", **status})

    @router.put("/api/candidate/resume")
    async def candidate_resume_put(
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> JSONResponse:
        require_admin(principal)
        raw = await request.body()
        if not raw:
            raise HTTPException(status_code=422, detail="empty resume")
        write_resume_pdf(settings, raw, db=request.app.state.db)
        request.app.state.db.add_event(
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="resume_put",
            note="stored resume PDF in postgres hub_blobs",
        )
        return _fresh_json(
            {"ok": True, "resume_url": "/api/candidate/resume", **candidate_status(settings, db=request.app.state.db)}
        )

    @router.get("/api/candidate")
    def candidate_admin_get(principal: Principal = Depends(principal_dep)) -> PlainTextResponse:
        require_admin(principal)
        text = candidate_blob_text()
        if text is None:
            path = resolve_candidate_path(settings)
            if path is None:
                raise HTTPException(
                    status_code=404,
                    detail="profiles/candidate.yaml missing; open /onboarding — do not invent one",
                )
            text = path.read_text(encoding="utf-8")
        return PlainTextResponse(text, media_type="text/yaml", headers=dict(NO_STORE))

    return router
