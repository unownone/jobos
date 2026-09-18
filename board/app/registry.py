"""Live skill + MCP registry HTTP API. GitHub seeds; maintainer proctors recordings."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth import Principal
from app.catalog import public_catalog
from app.db import utc_now
from app.memory_store import set_solidify_status
from app.mcp_store import McpStore, public_mcp
from app.queue import QueueService, claimant_id
from app.registry_seed import seed_hub_registries
from app.skill_store import (
    SKILL_ROLES,
    SkillStore,
    can_see_skill,
    is_admin,
    is_maintainer,
    owner_key,
    public_recording,
    public_skill,
    validate_skill_fields,
)
from app.tenant import COMPAT_ACCOUNT_ID, TenantContext

STATIC_DIR = Path(__file__).resolve().parent / "static"


class SkillIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    kind: str = "skill"
    role: str
    tags: list[str]
    platform: str | None = None
    match: dict[str, Any] | None = None
    inputs: list[str] | None = None
    outputs: list[str] | None = None
    body: str
    origin_ref: str | None = None
    parent_skill_id: str | None = None
    reproducible: bool = True


class SkillPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    kind: str | None = None
    role: str | None = None
    tags: list[str] | None = None
    platform: str | None = None
    match: dict[str, Any] | None = None
    inputs: list[str] | None = None
    outputs: list[str] | None = None
    body: str | None = None
    origin_ref: str | None = None
    reproducible: bool | None = None
    status: str | None = None


class RecordingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str | None = None
    slug: str | None = None
    name: str | None = None
    kind: str | None = None
    role: str | None = None
    tags: list[str] | None = None
    platform: str | None = None
    match: dict[str, Any] | None = None
    inputs: list[str] | None = None
    outputs: list[str] | None = None
    body: str | None = None
    origin_ref: str | None = None
    parent_skill_id: str | None = None
    reproducible: bool | None = None
    note: str | None = None


class ProctorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: str = Field(pattern="^(pass|fail)$")
    note: str | None = None
    evidence: dict[str, Any] | None = None


class DeclineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = None


def _store(request: Request, principal: Principal | None = None) -> SkillStore:
    db = request.app.state.db
    tenant = principal.tenant if principal is not None else TenantContext(COMPAT_ACCOUNT_ID)
    return SkillStore(db, tenant)


def _mcp_store(request: Request, principal: Principal | None = None) -> McpStore:
    tenant = principal.tenant if principal is not None else TenantContext(COMPAT_ACCOUNT_ID)
    return McpStore(request.app.state.db, tenant)


def _queue(request: Request) -> QueueService:
    return request.app.state.queue


def _require_maintainer(principal: Principal) -> None:
    if not is_maintainer(principal):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only maintainer or admin can do this",
        )


def _recording_payload_from_skill(skill: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "slug": skill["slug"],
        "name": skill["name"],
        "kind": skill.get("kind") or "skill",
        "role": skill["role"],
        "tags": list(skill.get("tags") or []),
        "platform": skill.get("platform") or "",
        "match": skill.get("match") or {},
        "inputs": list(skill.get("inputs") or []),
        "outputs": list(skill.get("outputs") or []),
        "body": skill.get("body") or "",
        "origin_ref": skill.get("origin_ref") or "",
        "parent_skill_id": skill.get("parent_skill_id"),
        "reproducible": bool(skill.get("reproducible", True)),
        "source_skill_id": skill["id"],
        "source_scope": skill.get("scope"),
    }
    if extra:
        payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


def _sync_memory_solidify(
    request: Request, recording: dict[str, Any], status: str, principal: Principal | None = None
) -> None:
    payload = recording.get("payload") or {}
    memory_id = payload.get("memory_id")
    if not memory_id:
        return
    set_solidify_status(
        request.app.state.db,
        str(memory_id),
        status=status,
        recording_id=recording.get("id"),
        principal=principal,
    )


def _promote_origin(payload: dict[str, Any], recording_id: str) -> tuple[str, str]:
    origin = str(payload.get("origin") or "recording")
    if origin not in {"recording", "mutation", "memory"}:
        origin = "recording"
    origin_ref = str(payload.get("origin_ref") or recording_id)
    if origin == "recording":
        origin_ref = recording_id
    return origin, origin_ref


def _claimed_recording(queue: QueueService, principal: Principal, recording: dict[str, Any]) -> None:
    if is_admin(principal):
        return
    item_id = recording.get("queue_item_id")
    if not item_id:
        raise HTTPException(status_code=409, detail="recording has no queue item to claim")
    item = queue.get(principal.tenant, item_id)
    if item is None:
        raise HTTPException(status_code=409, detail="queue item missing")
    who = claimant_id(principal)
    if item.get("status") != "claimed" or item.get("claimed_by") != who:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="claim skill.record before proctoring",
        )


def create_registry_router(principal_dep: Any) -> APIRouter:
    router = APIRouter(tags=["registry"])

    @router.get("/admin/skills")
    def skills_page(principal: Principal = Depends(principal_dep)) -> FileResponse:
        del principal
        return FileResponse(STATIC_DIR / "skills.html")

    @router.get("/api/registry/catalog")
    def list_public_catalog(
        request: Request,
        tag: str | None = None,
        role: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Approved shared skills + hosted MCP names. No auth."""
        if role and role not in SKILL_ROLES:
            raise HTTPException(status_code=422, detail=f"unknown role {role!r}")
        return public_catalog(_store(request), tag=tag, role=role, limit=limit)

    @router.get("/api/registry/skills")
    def list_skills(
        request: Request,
        principal: Principal = Depends(principal_dep),
        tag: str | None = None,
        role: str | None = None,
        platform: str | None = None,
        ats: str | None = None,
        url: str | None = None,
        scope: str | None = None,
        status_filter: Annotated[str | None, Query(alias="status")] = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        if role and role not in SKILL_ROLES:
            raise HTTPException(status_code=422, detail=f"unknown role {role!r}")
        store = _store(request, principal)
        items = store.list_visible(
            principal,
            tag=tag,
            role=role,
            platform=platform,
            ats=ats,
            url=url,
            scope=scope,
            status=status_filter,
            limit=limit,
        )
        return {"skills": [public_skill(item) for item in items], "count": len(items)}

    @router.get("/api/registry/mcps")
    def list_mcps(
        request: Request,
        principal: Principal = Depends(principal_dep),
        status_filter: Annotated[str | None, Query(alias="status")] = None,
        kind: str | None = None,
        role: str | None = None,
        capability: str | None = None,
        platform: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        store = _mcp_store(request, principal)
        items = store.list_visible(
            status=status_filter,
            kind=kind,
            role=role,
            capability=capability,
            platform=platform,
            limit=limit,
        )
        return {"mcps": [public_mcp(item) for item in items], "count": len(items)}

    @router.get("/api/registry/mcps/{mcp_id}")
    def get_mcp(
        mcp_id: str,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        store = _mcp_store(request, principal)
        item = store.get_by_id_or_slug(mcp_id)
        if item is None:
            raise HTTPException(status_code=404, detail="mcp not found")
        return {"mcp": public_mcp(item)}

    @router.get("/api/registry/skills/{skill_id}")
    def get_skill(
        skill_id: str,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        store = _store(request, principal)
        skill = store.get(skill_id)
        if skill is None or not can_see_skill(principal, skill):
            raise HTTPException(status_code=404, detail="skill not found")
        return {"skill": public_skill(skill)}

    @router.post("/api/registry/skills")
    def create_local_skill(
        body: SkillIn,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        store = _store(request, principal)
        fields = validate_skill_fields(body.model_dump())
        who = owner_key(principal)
        existing = store.get_local_by_slug(who, fields["slug"])
        if existing is not None:
            raise HTTPException(status_code=409, detail="local skill slug already exists")
        stored = store.insert(
            {
                **fields,
                "scope": "local",
                "owner_user_id": who,
                "status": "draft",
                "origin": "mutation",
                "created_by": who,
            }
        )
        request.app.state.db.add_event(
            principal.tenant,
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="skill_create_local",
            note=stored["slug"],
            fields={"skill_id": stored["id"], "slug": stored["slug"]},
        )
        return {"skill": public_skill(stored)}

    @router.patch("/api/registry/skills/{skill_id}")
    def patch_skill(
        skill_id: str,
        body: SkillPatch,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        store = _store(request, principal)
        skill = store.get(skill_id)
        if skill is None:
            raise HTTPException(status_code=404, detail="skill not found")
        who = owner_key(principal)
        if skill["scope"] == "local":
            if skill.get("owner_user_id") != who and not is_admin(principal):
                raise HTTPException(status_code=403, detail="cannot edit another bot's local skill")
        else:
            _require_maintainer(principal)
        incoming = body.model_dump(exclude_none=True)
        if "status" in incoming and incoming["status"] not in {
            "draft",
            "retired",
            "rejected",
            "approved",
        }:
            raise HTTPException(status_code=422, detail="invalid status")
        if skill["scope"] == "local" and incoming.get("status") == "approved" and not is_maintainer(principal):
            raise HTTPException(status_code=403, detail="local skills become shared only via maintainer promote")
        fields = validate_skill_fields({**skill, **incoming, "body": incoming.get("body", skill["body"])}, partial=True)
        patch = {k: fields[k] for k in fields if k in incoming or k in {"body", "tags", "match", "inputs", "outputs"}}
        if "status" in incoming:
            patch["status"] = incoming["status"]
        if "body" in incoming:
            patch["body"] = incoming["body"]
        stored = store.update(skill_id, patch)
        request.app.state.db.add_event(
            principal.tenant,
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="skill_patch",
            note=stored["slug"],
            fields={"skill_id": stored["id"], "keys": sorted(incoming)},
        )
        return {"skill": public_skill(stored)}

    @router.post("/api/registry/skills/{skill_id}/fork")
    def fork_skill(
        skill_id: str,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        store = _store(request, principal)
        skill = store.get(skill_id)
        if skill is None or not can_see_skill(principal, skill):
            raise HTTPException(status_code=404, detail="skill not found")
        who = owner_key(principal)
        existing = store.get_local_by_slug(who, skill["slug"])
        slug = skill["slug"]
        if existing is not None:
            slug = f"{skill['slug']}-local"
            n = 2
            while store.get_local_by_slug(who, slug) is not None:
                slug = f"{skill['slug']}-local-{n}"
                n += 1
        stored = store.insert(
            {
                "slug": slug,
                "name": skill["name"],
                "kind": skill.get("kind") or "skill",
                "role": skill["role"],
                "tags": list(skill.get("tags") or []),
                "platform": skill.get("platform") or "",
                "match": skill.get("match") or {},
                "inputs": list(skill.get("inputs") or []),
                "outputs": list(skill.get("outputs") or []),
                "body": skill.get("body") or "",
                "origin": "mutation",
                "origin_ref": skill.get("origin_ref") or "",
                "parent_skill_id": skill["id"],
                "reproducible": bool(skill.get("reproducible", True)),
                "scope": "local",
                "owner_user_id": who,
                "status": "draft",
                "created_by": who,
            }
        )
        request.app.state.db.add_event(
            principal.tenant,
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="skill_fork",
            note=stored["slug"],
            fields={"skill_id": stored["id"], "parent_skill_id": skill["id"]},
        )
        return {"skill": public_skill(stored)}

    @router.post("/api/registry/recordings")
    def submit_recording(
        body: RecordingIn,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        store = _store(request, principal)
        queue = _queue(request)
        who = owner_key(principal)
        source = None
        if body.skill_id:
            source = store.get(body.skill_id)
            if source is None or not can_see_skill(principal, source):
                raise HTTPException(status_code=404, detail="skill not found")
            if source["scope"] == "local" and source.get("owner_user_id") != who and not is_admin(principal):
                raise HTTPException(status_code=403, detail="cannot submit another bot's local skill")
        extra = body.model_dump(exclude_none=True)
        extra.pop("skill_id", None)
        extra.pop("note", None)
        if source is not None:
            payload = _recording_payload_from_skill(source, extra)
        else:
            fields = validate_skill_fields(
                {
                    "slug": body.slug,
                    "name": body.name,
                    "kind": body.kind or "skill",
                    "role": body.role,
                    "tags": body.tags,
                    "platform": body.platform,
                    "match": body.match,
                    "inputs": body.inputs,
                    "outputs": body.outputs,
                    "body": body.body,
                    "origin_ref": body.origin_ref,
                    "parent_skill_id": body.parent_skill_id,
                    "reproducible": body.reproducible if body.reproducible is not None else True,
                }
            )
            payload = {**fields, "source_skill_id": None, "source_scope": "new"}
        if body.note:
            payload["submitter_note"] = body.note
        recording = store.insert_recording(
            skill_id=body.skill_id,
            submitted_by=who,
            payload=payload,
        )
        item = queue.upsert(
            principal.tenant,
            kind="skill.record",
            job_id=None,
            payload={"recording_id": recording["id"], "slug": payload.get("slug")},
            actor_role=principal.role,
            actor=principal.actor,
        )
        recording = store.update_recording(recording["id"], {"queue_item_id": item["id"]})
        if body.skill_id and source is not None and source["scope"] == "local":
            store.update(source["id"], {"status": "recorded"})
        request.app.state.db.add_event(
            principal.tenant,
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="skill_record",
            note=str(payload.get("slug") or ""),
            fields={"recording_id": recording["id"], "queue_id": item["id"]},
        )
        return {"recording": public_recording(recording), "queue_item": {"id": item["id"], "kind": item["kind"]}}

    @router.get("/api/registry/recordings")
    def list_recordings(
        request: Request,
        principal: Principal = Depends(principal_dep),
        status_filter: Annotated[str | None, Query(alias="status")] = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        store = _store(request, principal)
        who = owner_key(principal)
        submitted_by = None if is_maintainer(principal) else who
        items = store.list_recordings(submitted_by=submitted_by, status=status_filter, limit=limit)
        return {"recordings": [public_recording(item) for item in items], "count": len(items)}

    @router.get("/api/registry/recordings/{recording_id}")
    def get_recording(
        recording_id: str,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        store = _store(request, principal)
        recording = store.get_recording(recording_id)
        if recording is None:
            raise HTTPException(status_code=404, detail="recording not found")
        if recording["submitted_by"] != owner_key(principal) and not is_maintainer(principal):
            raise HTTPException(status_code=404, detail="recording not found")
        return {"recording": public_recording(recording)}

    @router.post("/api/registry/recordings/{recording_id}/proctor")
    def proctor_recording(
        recording_id: str,
        body: ProctorIn,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        _require_maintainer(principal)
        store = _store(request, principal)
        queue = _queue(request)
        recording = store.get_recording(recording_id)
        if recording is None:
            raise HTTPException(status_code=404, detail="recording not found")
        if recording["status"] in {"promoted", "declined"}:
            raise HTTPException(status_code=409, detail="recording already closed")
        _claimed_recording(queue, principal, recording)
        passed = body.verdict == "pass"
        stored = store.update_recording(
            recording_id,
            {
                "status": "passed" if passed else "failed",
                "proctor_note": body.note or "",
                "proctor_evidence": body.evidence or {},
                "reviewed_by": owner_key(principal),
                "reviewed_at": utc_now(),
            },
        )
        _sync_memory_solidify(request, stored, "passed" if passed else "failed", principal)
        request.app.state.db.add_event(
            principal.tenant,
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="skill_proctor",
            note=body.verdict,
            fields={"recording_id": recording_id, "verdict": body.verdict},
        )
        return {"recording": public_recording(stored)}

    @router.post("/api/registry/recordings/{recording_id}/promote")
    def promote_recording(
        recording_id: str,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        _require_maintainer(principal)
        store = _store(request, principal)
        queue = _queue(request)
        recording = store.get_recording(recording_id)
        if recording is None:
            raise HTTPException(status_code=404, detail="recording not found")
        if recording["status"] != "passed":
            raise HTTPException(status_code=409, detail="proctor must pass before promote")
        _claimed_recording(queue, principal, recording)
        payload = dict(recording.get("payload") or {})
        fields = validate_skill_fields(payload)
        now = utc_now()
        who = owner_key(principal)
        origin, origin_ref = _promote_origin(payload, recording_id)
        existing = store.get_shared_by_slug(fields["slug"])
        shared_fields = {
            **fields,
            "scope": "shared",
            "owner_user_id": None,
            "status": "approved",
            "origin": origin,
            "origin_ref": origin_ref,
            "proctor_status": "passed",
            "proctor_note": recording.get("proctor_note") or "",
            "proctor_evidence": recording.get("proctor_evidence") or {},
            "approved_at": now,
            "approved_by": who,
            "created_by": recording.get("submitted_by") or who,
        }
        if existing is None:
            skill = store.insert(shared_fields)
        else:
            skill = store.update(
                existing["id"],
                {
                    **shared_fields,
                    "version": int(existing.get("version") or 1) + 1,
                },
            )
        stored = store.update_recording(recording_id, {"status": "promoted", "skill_id": skill["id"]})
        _sync_memory_solidify(request, stored, "promoted", principal)
        if recording.get("queue_item_id"):
            try:
                queue.ack(principal, recording["queue_item_id"])
            except HTTPException:
                pass
        request.app.state.db.add_event(
            principal.tenant,
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="skill_promote",
            note=skill["slug"],
            fields={"recording_id": recording_id, "skill_id": skill["id"]},
        )
        return {"recording": public_recording(stored), "skill": public_skill(skill)}

    @router.post("/api/registry/recordings/{recording_id}/decline")
    def decline_recording(
        recording_id: str,
        request: Request,
        principal: Principal = Depends(principal_dep),
        body: DeclineIn | None = None,
    ) -> dict[str, Any]:
        _require_maintainer(principal)
        store = _store(request, principal)
        queue = _queue(request)
        recording = store.get_recording(recording_id)
        if recording is None:
            raise HTTPException(status_code=404, detail="recording not found")
        if recording["status"] == "promoted":
            raise HTTPException(status_code=409, detail="already promoted")
        _claimed_recording(queue, principal, recording)
        note = (body.note if body is not None else None) or recording.get("proctor_note") or ""
        stored = store.update_recording(
            recording_id,
            {
                "status": "declined",
                "proctor_note": note,
                "reviewed_by": owner_key(principal),
                "reviewed_at": utc_now(),
            },
        )
        _sync_memory_solidify(request, stored, "declined", principal)
        if recording.get("queue_item_id"):
            try:
                queue.nack(principal, recording["queue_item_id"], requeue=False, note=note or "declined")
            except HTTPException:
                pass
        request.app.state.db.add_event(
            principal.tenant,
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="skill_decline",
            note=note,
            fields={"recording_id": recording_id},
        )
        return {"recording": public_recording(stored)}

    @router.post("/api/registry/seed")
    def seed_registry(
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        _require_maintainer(principal)
        pack = getattr(request.app.state, "pack", None)
        repo_root = pack.repo_root if pack is not None else None
        result = seed_hub_registries(
            request.app.state.db,
            repo_root,
            settings=request.app.state.settings,
            tenant=principal.tenant,
        )
        request.app.state.db.add_event(
            principal.tenant,
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="registry_seed",
            fields=result,
        )
        return {
            "ok": True,
            "counts": result["skills"],
            "skills": result["skills"],
            "mcps": result["mcps"],
        }

    return router
