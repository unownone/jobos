"""Hub memory pods: per-worker, per-track, and common. Recall every round; store sparingly."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict

from app.auth import Principal
from app.memory_policy import (
    RECALL_LIMIT_DEFAULT,
    RECALL_LIMIT_MAX,
    MemoryError,
    write_budget_hint,
)
from app.memory_store import (
    compact_recall,
    delete_item,
    grouped_recall,
    insert_item,
    list_items,
    pod_catalog,
    update_item,
)

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


def _raise_memory(exc: MemoryError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.detail},
    ) from exc


def create_memory_router(principal_dep) -> APIRouter:
    router = APIRouter(tags=["memory"])

    @router.get("/api/memory/pods")
    def memory_pods(principal: Principal = Depends(principal_dep)) -> dict[str, Any]:
        return {
            "pods": pod_catalog(principal),
            "write_policy": write_budget_hint(),
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

    @router.get("/admin/memory")
    def memory_page(principal: Principal = Depends(principal_dep)) -> FileResponse:
        del principal
        return FileResponse(STATIC_DIR / "memory.html")

    return router
