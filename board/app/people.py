"""Hiring-manager / contact records. Mirrors ledger/people. No secrets.

SQL lives in app.storage.repos.people. This module is the HTTP adapter.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth import Principal
from app.permissions import ensure_can_people
from app.storage.repos.people import (
    LIST_DEFAULT_LIMIT,
    PEOPLE_SCHEMA,
    PeopleRepo,
    ensure_people_schema,
    row_to_person,
)
from app.tenant import TenantContext

__all__ = [
    "PEOPLE_SCHEMA",
    "PersonIn",
    "PersonPatch",
    "create_people_router",
    "ensure_people_schema",
    "get_person",
    "insert_person",
    "list_people",
    "row_to_person",
    "update_person",
]

ID_RE = re.compile(r"^[a-z0-9]+__[a-zA-Z0-9._-]+$")
SLUG_RE = re.compile(r"[^a-z0-9]+")
SECRET_FRAGMENTS = (
    "token",
    "password",
    "secret",
    "api_key",
    "apikey",
    "cookie",
    "authorization",
    "key_hash",
    "blob_encrypted",
)

def _slug_id(company: str, name: str) -> str:
    slug = SLUG_RE.sub("-", f"{company}-{name}".lower()).strip("-")[:72]
    return f"person__{slug or 'contact'}"


def _reject_secrets(payload: dict[str, Any]) -> None:
    for key in payload:
        lowered = key.lower().replace("-", "_")
        if any(frag in lowered for frag in SECRET_FRAGMENTS):
            raise HTTPException(
                status_code=422,
                detail=f"people records cannot store secret field {key!r}",
            )


class PersonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str = Field(min_length=1)
    title: str | None = None
    company: str | None = None
    job_id: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    email_confidence: str | None = None
    do_not_contact: bool | None = False
    touches: list[Any] | None = None
    notes: str | None = None


class PersonPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    title: str | None = None
    company: str | None = None
    job_id: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    email_confidence: str | None = None
    do_not_contact: bool | None = None
    touches: list[Any] | None = None
    notes: str | None = None


def get_person(db: Any, tenant: TenantContext, person_id: str) -> dict[str, Any] | None:
    return PeopleRepo(db).get(tenant, person_id)


def list_people(
    db: Any,
    tenant: TenantContext,
    *,
    job_id: str | None = None,
    q: str | None = None,
    limit: int | None = LIST_DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    return PeopleRepo(db).list(tenant, job_id=job_id, q=q, limit=limit)


def insert_person(db: Any, tenant: TenantContext, payload: dict[str, Any]) -> dict[str, Any]:
    return PeopleRepo(db).insert(tenant, payload)


def update_person(
    db: Any, tenant: TenantContext, person_id: str, patch: dict[str, Any]
) -> dict[str, Any]:
    stored = PeopleRepo(db).update(tenant, person_id, patch)
    if stored is None:
        raise HTTPException(status_code=404, detail="person not found")
    return stored


def create_people_router(principal_dep: Any) -> APIRouter:
    router = APIRouter(tags=["people"])

    @router.get("/api/people")
    def people_list(
        request: Request,
        principal: Principal = Depends(principal_dep),
        job_id: str | None = None,
        q: str | None = None,
    ) -> dict[str, Any]:
        ensure_can_people(principal.role)
        db: Any = request.app.state.db
        people = list_people(db, principal.tenant, job_id=job_id, q=q)
        return {"people": people, "count": len(people)}

    @router.post("/api/people", status_code=201)
    def people_create(
        body: PersonIn,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_people(principal.role)
        payload = body.model_dump(exclude_none=True)
        _reject_secrets(payload)
        db: Any = request.app.state.db
        person_id = (payload.get("id") or "").strip() or _slug_id(
            str(payload.get("company") or ""),
            payload["name"],
        )
        if not ID_RE.match(person_id):
            raise HTTPException(status_code=422, detail="id must match {source}__{stable_id}")
        if get_person(db, principal.tenant, person_id):
            raise HTTPException(status_code=409, detail=f"person id already exists: {person_id}")
        payload["id"] = person_id
        stored = insert_person(db, principal.tenant, payload)
        event = db.add_event(
            principal.tenant,
            job_id=stored.get("job_id"),
            actor_role=principal.role,
            actor=principal.actor,
            action="person_create",
            note=stored["name"],
            fields={"person_id": stored["id"], "job_id": stored.get("job_id")},
        )
        return {"person": stored, "event": event}

    @router.get("/api/people/{person_id}")
    def people_get(
        person_id: str,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_people(principal.role)
        db: Any = request.app.state.db
        stored = get_person(db, principal.tenant, person_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="person not found")
        return {"person": stored}

    @router.patch("/api/people/{person_id}")
    def people_patch(
        person_id: str,
        body: PersonPatch,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_people(principal.role)
        patch = body.model_dump(exclude_none=True)
        _reject_secrets(patch)
        db: Any = request.app.state.db
        stored = update_person(db, principal.tenant, person_id, patch)
        event = db.add_event(
            principal.tenant,
            job_id=stored.get("job_id"),
            actor_role=principal.role,
            actor=principal.actor,
            action="person_patch",
            note="patched " + ", ".join(sorted(patch)),
            fields={"person_id": person_id, **{k: v for k, v in patch.items() if k != "touches"}},
        )
        return {"person": stored, "event": event}

    return router
