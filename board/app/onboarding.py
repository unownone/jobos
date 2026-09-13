"""Onboarding HTTP routes. Pack logic lives in pack.py; main.py includes this router."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.auth import Principal, authenticate, require_admin
from app.constants import canonical_track
from app.db import BoardDB
from app.identity import invite_status_error, verify_invite_secret
from app.pack import PackStore, normalize_relpath, skill_allowed
from app.settings import Settings
from app.skill_seed import seed_github_skills

TEXT_TYPES = {
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".sh": "text/x-shellscript; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".yaml": "text/yaml; charset=utf-8",
    ".yml": "text/yaml; charset=utf-8",
}


def _media_type(path) -> str:
    return TEXT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _unrestricted(principal: Principal | None) -> bool:
    if principal is None:
        return False
    if principal.kind == "admin" or principal.role == "admin":
        return True
    if principal.role == "maintenance" or principal.kind in {"viewer"}:
        return True
    return False


def create_onboarding_router(
    settings: Settings,
    db: BoardDB,
    pack: PackStore,
    principal_dep,
) -> APIRouter:
    router = APIRouter()

    def _invite_row(invite_id: str, secret: str) -> dict[str, Any]:
        row = db.get_invite(invite_id)
        if row is None:
            raise HTTPException(status_code=404, detail="invite not found")
        if not verify_invite_secret(row, secret):
            raise HTTPException(status_code=401, detail="invalid invite secret")
        err = invite_status_error(row)
        if err:
            raise err
        return row

    def require_onboarding_access(
        request: Request,
        invite_id: Annotated[str | None, Query()] = None,
        s: Annotated[str | None, Query()] = None,
        track: Annotated[str | None, Query()] = None,
        authorization: Annotated[str | None, Header()] = None,
        x_hub_key: Annotated[str | None, Header(alias="X-Hub-Key")] = None,
        x_role: Annotated[str | None, Header()] = None,
        x_token: Annotated[str | None, Header()] = None,
        x_actor: Annotated[str | None, Header()] = None,
        x_csrf: Annotated[str | None, Header(alias="X-CSRF")] = None,
        hub_session: Annotated[str | None, Cookie()] = None,
        hub_csrf: Annotated[str | None, Cookie()] = None,
    ) -> dict[str, Any]:
        if invite_id and s:
            row = _invite_row(invite_id, s)
            invited_track = row["track"]
            return {
                "track": invited_track,
                "principal": None,
                "invite": row,
                "unrestricted": False,
            }
        try:
            principal = authenticate(
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
            if exc.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail="unauthenticated onboarding without invite",
                ) from exc
            raise
        chosen = canonical_track(track) if track else None
        resolved = chosen or principal.track or ("discovery" if _unrestricted(principal) else None)
        if not resolved:
            raise HTTPException(status_code=422, detail="track required")
        return {
            "track": resolved,
            "principal": principal,
            "invite": None,
            "unrestricted": _unrestricted(principal),
        }

    def _file_response(rel: str) -> Response:
        path = pack.tree_file(rel)
        if path is None:
            raise HTTPException(status_code=404, detail="not found")
        media = _media_type(path)
        if media.startswith("text/") or media.startswith("application/json"):
            return PlainTextResponse(path.read_text(encoding="utf-8"), media_type=media)
        return FileResponse(path, media_type=media)

    @router.get("/api/onboarding")
    def get_onboarding(access: dict[str, Any] = Depends(require_onboarding_access)) -> dict[str, Any]:
        return pack.onboarding_payload(access["track"])

    @router.get("/api/docs/{path:path}")
    def get_doc(
        path: str,
        access: dict[str, Any] = Depends(require_onboarding_access),
    ) -> Response:
        rel = normalize_relpath(path)
        if rel is None:
            raise HTTPException(status_code=404, detail="not found")
        if rel.startswith("skills/") and not access["unrestricted"]:
            name = rel.split("/")[1] if "/" in rel else ""
            if not skill_allowed(access["track"], name, unrestricted=False):
                raise HTTPException(status_code=404, detail="not found")
        return _file_response(rel)

    @router.get("/api/skills/{name}/{file:path}")
    def get_skill(
        name: str,
        file: str,
        access: dict[str, Any] = Depends(require_onboarding_access),
    ) -> Response:
        if not skill_allowed(access["track"], name, unrestricted=access["unrestricted"]):
            raise HTTPException(status_code=404, detail="not found")
        rel = normalize_relpath(f"skills/{name}/{file}")
        if rel is None or not rel.startswith(f"skills/{name}/"):
            raise HTTPException(status_code=404, detail="not found")
        return _file_response(rel)

    @router.get("/api/mcp/example.json")
    def get_mcp_example(access: dict[str, Any] = Depends(require_onboarding_access)) -> Response:
        return _file_response("mcp/mcp.example.json")

    @router.get("/api/mcp/hosted/{name}.json")
    def get_hosted_mcp(
        name: str,
        access: dict[str, Any] = Depends(require_onboarding_access),
    ) -> Response:
        rel = normalize_relpath(f"mcp/hosted/{name}.json")
        if rel is None:
            raise HTTPException(status_code=404, detail="not found")
        return _file_response(rel)

    @router.get("/api/scripts/{name}")
    def get_script(
        name: str,
        access: dict[str, Any] = Depends(require_onboarding_access),
    ) -> Response:
        rel = normalize_relpath(f"scripts/{name}")
        if rel is None:
            raise HTTPException(status_code=404, detail="not found")
        return _file_response(rel)

    @router.get("/api/packs/current/skills.zip")
    def get_skills_zip(access: dict[str, Any] = Depends(require_onboarding_access)) -> FileResponse:
        path = pack.zip_path(access["track"])
        if path is None:
            raise HTTPException(status_code=404, detail="pack zip not found")
        filename = f"skills-{access['track']}.zip"
        return FileResponse(path, media_type="application/zip", filename=filename)

    @router.post("/api/packs/rebuild")
    def rebuild_pack(principal: Principal = Depends(principal_dep)) -> dict[str, Any]:
        if principal.role not in {"admin", "maintenance"} and principal.kind != "admin":
            require_admin(principal)
        meta = pack.rebuild()
        counts = seed_github_skills(db, pack.repo_root, settings=settings)
        db.add_event(
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="pack_rebuild",
            fields={
                "pack_sha": meta.pack_sha,
                "git_sha": meta.git_sha,
                "skill_seed": counts,
            },
        )
        return {
            "ok": True,
            "pack_sha": meta.pack_sha,
            "git_sha": meta.git_sha,
            "built_at": meta.built_at,
            "catalog_updated_at": meta.catalog_updated_at,
            "files": meta.files,
            "skill_seed": counts,
        }

    return router
