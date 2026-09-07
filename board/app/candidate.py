"""Candidate public slice and resume download. Never invent profiles/candidate.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

from app.auth import Principal, require_admin
from app.pack import public_candidate
from app.permissions import ensure_can_resume
from app.settings import Settings

HUB_CANDIDATE_REL = Path("data") / "profiles" / "candidate.yaml"
HUB_RESUME_NAME = "candidate-resume.pdf"


def hub_candidate_path(settings: Settings) -> Path:
    return settings.board_dir / HUB_CANDIDATE_REL


def hub_resume_path(settings: Settings) -> Path:
    return settings.board_dir / "data" / HUB_RESUME_NAME


def resolve_candidate_path(settings: Settings) -> Path | None:
    local = hub_candidate_path(settings)
    if local.is_file():
        return local
    repo = (settings.repo_root or settings.board_dir.parent) / "profiles" / "candidate.yaml"
    if repo.is_file():
        return repo
    return None


def resolve_resume_path(settings: Settings) -> Path | None:
    local = hub_resume_path(settings)
    if local.is_file():
        return local
    assets = (settings.repo_root or settings.board_dir.parent) / "assets" / "resume"
    if assets.is_dir():
        pdfs = sorted(assets.glob("*.pdf"))
        if pdfs:
            return pdfs[0]
    return None


def create_candidate_router(settings: Settings, principal_dep: Any) -> APIRouter:
    router = APIRouter(tags=["candidate"])

    @router.get("/api/candidate/public")
    def candidate_public(principal: Principal = Depends(principal_dep)) -> dict[str, Any]:
        del principal
        repo_root = settings.repo_root or settings.board_dir.parent
        local = hub_candidate_path(settings)
        if local.is_file():
            payload = public_candidate(settings.board_dir / "data")
            payload["source"] = "hub-data"
        else:
            payload = public_candidate(repo_root)
            payload["source"] = "repo" if payload.get("present") else "missing"
        resume = resolve_resume_path(settings)
        payload["resume_url"] = "/api/candidate/resume" if resume else None
        return payload

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
        dest = hub_candidate_path(settings)
        dest.parent.mkdir(parents=True, exist_ok=True)
        raw = await request.body()
        if not raw.strip():
            raise HTTPException(status_code=422, detail="empty candidate yaml")
        dest.write_bytes(raw)
        request.app.state.db.add_event(
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="candidate_put",
            note="stored gitignored hub candidate.yaml",
        )
        return {"ok": True, "present": True, "path": "board/data/profiles/candidate.yaml"}

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
        return {"ok": True, "resume_url": "/api/candidate/resume"}

    @router.get("/api/candidate")
    def candidate_admin_hint(principal: Principal = Depends(principal_dep)) -> PlainTextResponse:
        require_admin(principal)
        path = resolve_candidate_path(settings)
        if path is None:
            raise HTTPException(status_code=404, detail="profiles/candidate.yaml missing; do not invent one")
        return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/yaml")

    return router
