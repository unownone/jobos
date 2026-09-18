"""Hiring-manager / contact records. Mirrors ledger/people. No secrets."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth import Principal
from app.permissions import ensure_can_people
from app.tenant import TenantContext

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

PEOPLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    account_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    title TEXT,
    company TEXT,
    job_id TEXT,
    linkedin_url TEXT,
    email TEXT,
    email_confidence TEXT,
    do_not_contact INTEGER NOT NULL DEFAULT 0,
    touches_json TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account_id, id)
);

CREATE INDEX IF NOT EXISTS idx_people_job ON people(account_id, job_id);
CREATE INDEX IF NOT EXISTS idx_people_company ON people(account_id, company);
"""


def ensure_people_schema(conn: Any) -> None:
    conn.executescript(PEOPLE_SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def row_to_person(row: Any) -> dict[str, Any]:
    data = dict(row)
    touches = json.loads(data["touches_json"] or "[]")
    return {
        "id": data["id"],
        "name": data["name"],
        "title": data["title"] or "",
        "company": data["company"] or "",
        "job_id": data["job_id"] or None,
        "linkedin_url": data["linkedin_url"] or "",
        "email": data["email"] or "",
        "email_confidence": data["email_confidence"] or "",
        "do_not_contact": bool(data["do_not_contact"]),
        "touches": touches if isinstance(touches, list) else [],
        "notes": data["notes"] or "",
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }


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
    cur = db.conn.execute(
        "SELECT * FROM people WHERE account_id = ? AND id = ?",
        (tenant.account_id, person_id),
    )
    row = cur.fetchone()
    return row_to_person(row) if row else None


def list_people(
    db: Any,
    tenant: TenantContext,
    *,
    job_id: str | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM people WHERE account_id = ?"
    args: list[Any] = [tenant.account_id]
    if job_id:
        sql += " AND job_id = ?"
        args.append(job_id)
    if q:
        sql += " AND (name LIKE ? OR company LIKE ? OR title LIKE ?)"
        like = f"%{q}%"
        args.extend([like, like, like])
    sql += " ORDER BY updated_at DESC"
    cur = db.conn.execute(sql, args)
    return [row_to_person(row) for row in cur.fetchall()]


def insert_person(db: Any, tenant: TenantContext, payload: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    db.conn.execute(
        """
        INSERT INTO people (
            account_id, id, name, title, company, job_id, linkedin_url, email, email_confidence,
            do_not_contact, touches_json, notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tenant.account_id,
            payload["id"],
            payload["name"],
            payload.get("title") or "",
            payload.get("company") or "",
            payload.get("job_id") or None,
            payload.get("linkedin_url") or "",
            payload.get("email") or "",
            payload.get("email_confidence") or "",
            1 if payload.get("do_not_contact") else 0,
            json.dumps(payload.get("touches") or [], ensure_ascii=False),
            payload.get("notes") or "",
            payload.get("created_at") or now,
            payload.get("updated_at") or now,
        ),
    )
    db.conn.commit()
    stored = get_person(db, tenant, payload["id"])
    assert stored is not None
    return stored


def update_person(
    db: Any, tenant: TenantContext, person_id: str, patch: dict[str, Any]
) -> dict[str, Any]:
    current = get_person(db, tenant, person_id)
    if current is None:
        raise HTTPException(status_code=404, detail="person not found")
    merged = {**current, **patch}
    db.conn.execute(
        """
        UPDATE people SET
            name=?, title=?, company=?, job_id=?, linkedin_url=?, email=?,
            email_confidence=?, do_not_contact=?, touches_json=?, notes=?, updated_at=?
        WHERE account_id=? AND id=?
        """,
        (
            merged["name"],
            merged.get("title") or "",
            merged.get("company") or "",
            merged.get("job_id") or None,
            merged.get("linkedin_url") or "",
            merged.get("email") or "",
            merged.get("email_confidence") or "",
            1 if merged.get("do_not_contact") else 0,
            json.dumps(merged.get("touches") or [], ensure_ascii=False),
            merged.get("notes") or "",
            _now(),
            tenant.account_id,
            person_id,
        ),
    )
    db.conn.commit()
    stored = get_person(db, tenant, person_id)
    assert stored is not None
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
