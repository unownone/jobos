"""Hub memory pods: per-worker, per-track, and common. Recall every round; store sparingly."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth import Principal
from app.memory_policy import (
    RECALL_LIMIT_DEFAULT,
    RECALL_LIMIT_MAX,
    MemoryDenied,
    MemoryError,
    MemoryNotFound,
    can_read_pod,
    is_inspector,
    kinds_for_scope,
    pod_scope,
    worker_id,
    write_budget_hint,
)
from app.memory_store import (
    OPEN_SOLIDIFY_STATUSES,
    compact_recall,
    delete_item,
    get_item,
    grouped_recall,
    insert_item,
    list_items,
    move_item,
    pod_catalog,
    public_item,
    row_to_item,
    set_solidify_status,
    skill_draft_from_memory,
    update_item,
)
from app.skill_store import SkillStore, owner_key, public_recording, validate_skill_fields

STATIC_DIR = Path(__file__).resolve().parent / "static"


class MemoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pod: str | None = "worker"
    kind: str
    title: str
    body: str
    job_id: str | None = None
    company: str | None = None
    tags: list[str] | None = None
    importance: int | None = 2
    pinned: bool = False
    ttl_days: int | None = None


class MemoryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    body: str | None = None
    pinned: bool | None = None
    expires_at: str | None = None
    forget: bool = False


class MemoryMoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    pod: str
    keep_original: bool = Field(default=False, alias="copy")
    kind: str | None = None


class SolidifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str | None = None
    name: str | None = None
    role: str | None = None
    tags: list[str] | None = None
    platform: str | None = None
    match: dict[str, Any] | None = None
    note: str | None = None


def _raise_memory(exc: MemoryError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.detail},
    ) from exc


def _skill_store(request: Request, principal: Principal) -> SkillStore:
    return SkillStore(request.app.state.db, principal.tenant)


def create_memory_router(principal_dep) -> APIRouter:
    router = APIRouter(tags=["memory"])

    @router.get("/api/memory/pods")
    def memory_pods(principal: Principal = Depends(principal_dep)) -> dict[str, Any]:
        catalog = pod_catalog(principal)
        return {
            "pods": catalog,
            "write_policy": write_budget_hint(),
            "kinds": {
                "worker": sorted(kinds_for_scope("worker")),
                "track": sorted(kinds_for_scope("track")),
                "common": sorted(kinds_for_scope("common")),
            },
        }

    @router.get("/api/memory/recall")
    def memory_recall(
        request: Request,
        q: str | None = None,
        job_id: str | None = None,
        company: str | None = None,
        limit: int = RECALL_LIMIT_DEFAULT,
        compact: bool = False,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        db = request.app.state.db
        cap = max(1, min(limit, RECALL_LIMIT_MAX))
        try:
            if compact:
                return compact_recall(
                    db, principal, q=q, job_id=job_id, company=company, limit=cap
                )
            return grouped_recall(
                db, principal, q=q, job_id=job_id, company=company, limit=cap
            )
        except MemoryError as exc:
            _raise_memory(exc)
            raise

    @router.get("/api/memory/items")
    def memory_list(
        request: Request,
        pod: str | None = None,
        kind: str | None = None,
        q: str | None = None,
        job_id: str | None = None,
        company: str | None = None,
        limit: int = RECALL_LIMIT_DEFAULT,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        db = request.app.state.db
        try:
            items = list_items(
                db,
                principal,
                pod=pod,
                kind=kind,
                q=q,
                job_id=job_id,
                company=company,
                limit=limit,
            )
        except MemoryError as exc:
            _raise_memory(exc)
            raise
        return {"items": items, "count": len(items)}

    @router.post("/api/memory/items")
    def memory_create(
        request: Request,
        body: MemoryIn,
        principal: Principal = Depends(principal_dep),
    ) -> JSONResponse:
        db = request.app.state.db
        try:
            item = insert_item(
                db,
                principal,
                pod=body.pod,
                kind=body.kind,
                title=body.title,
                body=body.body,
                job_id=body.job_id,
                company=body.company,
                tags=body.tags,
                importance=body.importance,
                pinned=body.pinned,
                ttl_days=body.ttl_days,
            )
        except MemoryError as exc:
            _raise_memory(exc)
            raise
        deduped = bool(item.get("deduped"))
        return JSONResponse(
            status_code=200 if deduped else 201,
            content={"item": item, "status": "exists" if deduped else "stored"},
        )

    @router.patch("/api/memory/items/{item_id}")
    def memory_patch(
        request: Request,
        item_id: str,
        body: MemoryPatch,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        db = request.app.state.db
        try:
            item = update_item(
                db,
                principal,
                item_id,
                title=body.title,
                body=body.body,
                pinned=body.pinned,
                expires_at=body.expires_at,
                forget=body.forget,
            )
        except MemoryError as exc:
            _raise_memory(exc)
            raise
        return {"item": item}

    @router.delete("/api/memory/items/{item_id}")
    def memory_delete(
        request: Request,
        item_id: str,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        db = request.app.state.db
        try:
            return delete_item(db, principal, item_id)
        except MemoryError as exc:
            _raise_memory(exc)
            raise

    @router.post("/api/memory/items/{item_id}/move")
    def memory_move(
        request: Request,
        item_id: str,
        body: MemoryMoveIn,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        db = request.app.state.db
        try:
            item = move_item(
                db,
                principal,
                item_id,
                pod=body.pod,
                copy=body.keep_original,
                kind=body.kind,
            )
        except MemoryError as exc:
            _raise_memory(exc)
            raise
        db.add_event(
            principal.tenant,
            job_id=item.get("job_id"),
            actor_role=principal.role,
            actor=principal.actor,
            action="memory_copy" if body.keep_original else "memory_move",
            note=item.get("pod") or body.pod,
            fields={"memory_id": item.get("id"), "from": item_id, "pod": item.get("pod")},
        )
        return {"item": item, "copied": body.keep_original}

    @router.post("/api/memory/items/{item_id}/solidify")
    def memory_solidify(
        item_id: str,
        request: Request,
        principal: Principal = Depends(principal_dep),
        body: SolidifyIn | None = None,
    ) -> dict[str, Any]:
        db = request.app.state.db
        raw = get_item(db, item_id, principal=principal)
        if raw is None or not can_read_pod(principal, raw["pod"]):
            _raise_memory(MemoryNotFound("memory item not found"))
            raise
        stored = row_to_item(raw)
        owns = stored["created_by"] == worker_id(principal)
        if not owns and not is_inspector(principal):
            _raise_memory(MemoryDenied("only the author or maintainer can solidify this memory"))
            raise
        if pod_scope(stored["pod"]) == "worker":
            _raise_memory(MemoryDenied("private worker notes cannot become skills"))
            raise
        existing_id = stored.get("recording_id")
        store = _skill_store(request, principal)
        if existing_id and (stored.get("solidify_status") or "none") in OPEN_SOLIDIFY_STATUSES:
            recording = store.get_recording(existing_id)
            if recording is not None:
                return {
                    "item": {
                        **stored,
                        "solidify_status": stored.get("solidify_status") or "queued",
                        "recording_id": existing_id,
                    },
                    "recording": public_recording(recording),
                    "status": "exists",
                }
        extra = (body.model_dump(exclude_none=True) if body is not None else {})
        note = extra.pop("note", None)
        try:
            draft = skill_draft_from_memory(stored)
        except MemoryError as exc:
            _raise_memory(exc)
            raise
        draft.update({key: value for key, value in extra.items() if value is not None})
        fields = validate_skill_fields(draft)
        payload = {
            **fields,
            "origin": "memory",
            "origin_ref": stored["id"],
            "memory_id": stored["id"],
            "memory_pod": stored["pod"],
            "memory_kind": stored.get("kind"),
            "source_skill_id": None,
            "source_scope": "memory",
        }
        if note:
            payload["submitter_note"] = note
        who = owner_key(principal)
        recording = store.insert_recording(skill_id=None, submitted_by=who, payload=payload)
        queue = request.app.state.queue
        item = queue.upsert(
            principal.tenant,
            kind="skill.record",
            job_id=None,
            payload={"recording_id": recording["id"], "slug": payload.get("slug"), "memory_id": stored["id"]},
            actor_role=principal.role,
            actor=principal.actor,
        )
        recording = store.update_recording(recording["id"], {"queue_item_id": item["id"]})
        set_solidify_status(
            db, stored["id"], status="queued", recording_id=recording["id"], principal=principal
        )
        db.add_event(
            principal.tenant,
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="memory_solidify",
            note=str(payload.get("slug") or ""),
            fields={"memory_id": stored["id"], "recording_id": recording["id"], "queue_id": item["id"]},
        )
        return {
            "item": public_item(db, stored["id"], principal=principal),
            "recording": public_recording(recording),
            "queue_item": {"id": item["id"], "kind": item["kind"]},
            "status": "queued",
        }

    @router.get("/admin/memory")
    def memory_page(principal: Principal = Depends(principal_dep)) -> FileResponse:
        del principal
        return FileResponse(STATIC_DIR / "memory.html")

    return router
