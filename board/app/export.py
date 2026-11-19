"""On-demand git ledger export. Hub SQLite stays live SoT. Strips secrets."""

from __future__ import annotations

import io
import json
import tarfile
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.auth import Principal
from app.db import BoardDB
from app.people import list_people
from app.permissions import ensure_can_export
from app.tenant import TenantContext

SECRET_KEY_FRAGMENTS = (
    "token",
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "key_hash",
    "csrf",
    "blob_encrypted",
    "connector",
    "board_token",
)

# list_jobs(None) reads every row. Export keeps an explicit bound.
LEDGER_JOB_LIMIT = 100_000

JOB_EXPORT_KEYS = (
    "id",
    "company",
    "title",
    "location",
    "remote",
    "url",
    "apply_url",
    "apply_kind",
    "ats",
    "req_id",
    "sources",
    "status",
    "score",
    "owners",
    "apply_packet",
    "outreach_packet",
    "research",
    "proof",
    "notes",
    "rejection",
    "description",
    "expectations",
    "pay",
    "posted_at",
    "conflicts",
    "created_at",
    "updated_at",
)


def _is_secret_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(frag in lowered for frag in SECRET_KEY_FRAGMENTS)


def strip_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: strip_secrets(v) for k, v in value.items() if not _is_secret_key(str(k))}
    if isinstance(value, list):
        return [strip_secrets(item) for item in value]
    if isinstance(value, str):
        if "BOARD_TOKEN" in value or value.startswith("jh_agt_") or value.startswith("jh_own_"):
            return ""
        return value
    return value


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value)
    if text == "":
        return '""'
    if any(ch in text for ch in ":#{}[]&*!|>'\"%@`\n"):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def dump_yaml(value: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{key}:")
                nested = dump_yaml(item, indent + 1)
                lines.append(nested if nested.endswith("\n") else nested)
            elif isinstance(item, list) and not item:
                lines.append(f"{pad}{key}: []")
            elif isinstance(item, dict) and not item:
                lines.append(f"{pad}{key}: {{}}")
            else:
                lines.append(f"{pad}{key}: {_yaml_scalar(item)}")
        return "\n".join(lines) + ("\n" if indent == 0 else "")
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                dumped = dump_yaml(item, indent + 1).rstrip("\n")
                first, *rest = dumped.splitlines() or [""]
                lines.append(f"{pad}- {first.lstrip()}")
                for extra in rest:
                    lines.append(extra)
            else:
                lines.append(f"{pad}- {_yaml_scalar(item)}")
        return "\n".join(lines) + ("\n" if indent == 0 else "")
    return _yaml_scalar(value)


def job_for_export(job: dict[str, Any]) -> dict[str, Any]:
    payload = {key: job.get(key) for key in JOB_EXPORT_KEYS if key in job}
    return strip_secrets(payload)


def person_for_export(person: dict[str, Any]) -> dict[str, Any]:
    return strip_secrets(
        {
            "id": person["id"],
            "name": person["name"],
            "title": person.get("title") or "",
            "company": person.get("company") or "",
            "job_id": person.get("job_id") or "",
            "linkedin_url": person.get("linkedin_url") or "",
            "email": person.get("email") or "",
            "email_confidence": person.get("email_confidence") or "",
            "do_not_contact": bool(person.get("do_not_contact")),
            "touches": person.get("touches") or [],
            "notes": person.get("notes") or "",
        }
    )


def event_for_export(event: dict[str, Any]) -> dict[str, Any]:
    return strip_secrets(
        {
            "ts": event.get("ts"),
            "job_id": event.get("job_id"),
            "actor": event.get("actor"),
            "role": event.get("actor_role") or event.get("role"),
            "from": event.get("from_status") or event.get("from"),
            "to": event.get("to_status") or event.get("to"),
            "action": event.get("action"),
            "note": event.get("note"),
        }
    )


def render_index(jobs: list[dict[str, Any]]) -> str:
    lines = [
        "# Ledger INDEX",
        "",
        "Exported from Job Hub SQLite (live SoT). Git is the airgap copy.",
        "",
        "## Active operators",
        "",
        "| role | name | scope | since |",
        "| --- | --- | --- | --- |",
        "| discovery | _see Hub presence_ | all portals | |",
        "| apply | _see Hub presence_ | all ATS | |",
        "| outreach | _see Hub presence_ | email + linkedin_dm | |",
        "| maintainer | _see Hub presence_ | skills + lists + hunt board | |",
        "",
        "## Jobs",
        "",
        "| id | company | title | source | status | score | owner | next |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    if not jobs:
        lines.append("| _empty_ | | | | | | | |")
    else:
        for job in jobs:
            sources = job.get("sources") or []
            source = ",".join(sources) if isinstance(sources, list) else str(sources)
            owners = job.get("owners") or {}
            owner = ""
            if isinstance(owners, dict):
                owner = str(
                    owners.get("discovery") or owners.get("apply") or owners.get("outreach") or ""
                )
            lines.append(
                "| {id} | {company} | {title} | {source} | {status} | {score} | {owner} | |".format(
                    id=str(job.get("id") or "").replace("|", "/"),
                    company=str(job.get("company") or "").replace("|", "/"),
                    title=str(job.get("title") or "").replace("|", "/"),
                    source=str(source).replace("|", "/"),
                    status=str(job.get("status") or ""),
                    score=str(job.get("score") or ""),
                    owner=owner.replace("|", "/"),
                )
            )
    lines.append("")
    return "\n".join(lines)


def build_ledger_files(db: BoardDB, tenant: TenantContext) -> dict[str, str]:
    jobs = [job_for_export(job) for job in db.list_jobs(tenant, limit=LEDGER_JOB_LIMIT)]
    people = [person_for_export(person) for person in list_people(db, tenant)]
    events = [event_for_export(event) for event in db.list_events(tenant, limit=10000)]
    files: dict[str, str] = {
        "ledger/INDEX.md": render_index(jobs),
        "ledger/events.jsonl": "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in events),
    }
    for job in jobs:
        job_id = str(job.get("id") or "unknown")
        files[f"ledger/jobs/{job_id}.yaml"] = dump_yaml(job)
    for person in people:
        person_id = str(person.get("id") or "unknown")
        files[f"ledger/people/{person_id}.yaml"] = dump_yaml(person)
    if not people:
        files["ledger/people/.keep"] = ""
    blob = "\n".join(files.values())
    if "BOARD_TOKEN" in blob or "blob_encrypted" in blob:
        raise HTTPException(status_code=500, detail="export refused: secret residue")
    return files


def tar_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = int(datetime.now(timezone.utc).timestamp())
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def create_export_router(principal_dep: Any) -> APIRouter:
    router = APIRouter(tags=["export"])

    @router.get("/api/export/ledger")
    def export_ledger(
        request: Request,
        principal: Principal = Depends(principal_dep),
        format: Annotated[str, Query()] = "tar",
    ) -> Any:
        ensure_can_export(principal.role)
        fmt = (format or "tar").strip().lower()
        if fmt not in {"tar", "json"}:
            raise HTTPException(status_code=422, detail="format must be tar or json")
        db: BoardDB = request.app.state.db
        files = build_ledger_files(db, principal.tenant)
        db.add_event(
            principal.tenant,
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="ledger_export",
            note=f"files={len(files)} format={fmt}",
        )
        if fmt == "json":
            jobs = [job_for_export(job) for job in db.list_jobs(principal.tenant, limit=LEDGER_JOB_LIMIT)]
            people = [person_for_export(person) for person in list_people(db, principal.tenant)]
            events = [event_for_export(event) for event in db.list_events(principal.tenant, limit=10000)]
            return {
                "jobs": jobs,
                "people": people,
                "events": events,
                "files": sorted(files),
                "source": "hub-postgres",
            }
        payload = tar_bytes(files)
        return StreamingResponse(
            io.BytesIO(payload),
            media_type="application/gzip",
            headers={"Content-Disposition": 'attachment; filename="ledger-export.tar.gz"'},
        )

    return router
