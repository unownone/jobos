"""A2A protocol (https://a2a-protocol.org/latest/) for cross-agent Hub communication.

JSON-RPC 2.0 over HTTP. Agent Cards at /.well-known/agent-card.json.
This is the interoperable plane for agents outside this repo (LangGraph, Claude,
Cursor, CrewAI, custom runtimes). Hub inbox `/api/messages` remains the convenience
API and is the storage backend for A2A message/send.
"""

from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.request
from typing import Any, Callable
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth import Principal
from app.bootstrap import public_base
from app.constants import TRACKS, canonical_track
from app.db import BoardDB
from app.message_store import insert_message, sender_id
from app.profile import candidate_onboarded, candidate_status
from app.settings import Settings
from app.a2a_store import (
    get_peer,
    get_peer_by_card_url,
    get_task,
    insert_peer,
    insert_task,
    list_peers,
    list_tasks,
    touch_peer,
    update_task,
)

PROTOCOL_VERSION = "0.3.0"
JSONRPC_VERSION = "2.0"

RPC_PARSE = -32700
RPC_INVALID_REQUEST = -32600
RPC_METHOD_NOT_FOUND = -32601
RPC_INVALID_PARAMS = -32602
RPC_INTERNAL = -32603
RPC_TASK_NOT_FOUND = -32001
RPC_TASK_NOT_CANCELABLE = -32002
# Hub-specific (A2A reserved -32001..-32008 for spec errors).
RPC_CANDIDATE_REQUIRED = -32090
RPC_AUTH_REQUIRED = -32091

MESSAGE_TYPES = ("note", "block", "handoff", "question")
TRACK_SKILLS = {
    "discovery": {
        "id": "hub.discovery",
        "name": "Job discovery",
        "description": "Find, enrich, score, and write apply packets. Never Easy Apply.",
        "tags": ["jobs", "discovery", "shortlist"],
        "examples": ["Search RemoteOK for Staff Backend Engineer and write an apply packet."],
    },
    "application": {
        "id": "hub.application",
        "name": "Job application",
        "description": "Submit from an apply packet with proof. Do not invent jobs.",
        "tags": ["jobs", "apply", "ats"],
        "examples": ["Apply to the Greenhouse packet on job remoteok__123."],
    },
    "outreach": {
        "id": "hub.outreach",
        "name": "Outreach",
        "description": "Email with resume PDF plus LinkedIn DM. No SMS/WhatsApp/InMail.",
        "tags": ["jobs", "email", "linkedin"],
        "examples": ["Send a 15-minute-chat email with the resume attached."],
    },
    "maintenance": {
        "id": "hub.maintenance",
        "name": "Hub maintenance",
        "description": "Skill/MCP catalog, packs, hygiene. Not job sourcing.",
        "tags": ["catalog", "hygiene"],
        "examples": ["Rebuild the skill pack after a catalog pass."],
    },
}
HANDOFF_SKILL = {
    "id": "hub.handoff",
    "name": "Cross-track handoff",
    "description": "Agent-to-agent note, block, handoff, or question. Not employer mail.",
    "tags": ["a2a", "handoff", "inbox"],
    "examples": ["Handoff apply_ready packet for Acme to the application track."],
}


class PeerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_url: str = Field(min_length=8)
    name: str | None = None


class PeerSendIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str | None = None
    message: dict[str, Any] | None = None
    skill_id: str | None = None
    metadata: dict[str, Any] | None = None


def _jsonrpc_error(rpc_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": rpc_id, "error": err}


def _jsonrpc_result(rpc_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": rpc_id, "result": result}


def _text_part(text: str) -> dict[str, Any]:
    return {"kind": "text", "text": text}


def _data_part(data: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "data", "data": data}


def _agent_message(text: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [_text_part(text)]
    if data:
        parts.append(_data_part(data))
    return {
        "kind": "message",
        "role": "agent",
        "parts": parts,
        "messageId": str(uuid4()),
    }


def _task_object(
    *,
    task_id: str,
    context_id: str,
    state: str,
    message: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    status: dict[str, Any] = {"state": state}
    if message is not None:
        status["message"] = message
    if timestamp:
        status["timestamp"] = timestamp
    payload: dict[str, Any] = {
        "kind": "task",
        "id": task_id,
        "contextId": context_id,
        "status": status,
        "history": history or [],
        "artifacts": artifacts or [],
    }
    if metadata:
        payload["metadata"] = metadata
    return payload


def agent_card(settings: Settings, *, track: str | None = None, extended: bool = False) -> dict[str, Any]:
    base = public_base(settings).rstrip("/")
    url = f"{base}/a2a"
    if track:
        url = f"{base}/a2a/{canonical_track(track) or track}"
    skills = [HANDOFF_SKILL]
    if track:
        key = canonical_track(track) or track
        if key in TRACK_SKILLS:
            skills = [TRACK_SKILLS[key], HANDOFF_SKILL]
    else:
        skills = [*TRACK_SKILLS.values(), HANDOFF_SKILL]
    status = candidate_status(settings)
    card: dict[str, Any] = {
        "protocolVersion": PROTOCOL_VERSION,
        "name": "Job Hub" if not track else f"Job Hub / {track}",
        "description": (
            "Distributed job-search coordination plane. Discovery, application, outreach, "
            "and maintenance tracks talk through A2A. Not employer email or SMS."
        ),
        "url": url,
        "preferredTransport": "JSONRPC",
        "additionalInterfaces": [{"url": url, "transport": "JSONRPC"}],
        "provider": {
            "organization": "Job Apply OS",
            "url": base or "https://a2a-protocol.org/latest/",
        },
        "version": "1.0.0",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": True,
        },
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": skills,
        "supportsAuthenticatedExtendedCard": True,
        "securitySchemes": {
            "bearer": {"type": "http", "scheme": "bearer", "bearerFormat": "API Key"},
        },
        "security": [{"bearer": []}],
    }
    if extended:
        card["metadata"] = {
            "tracks": list(TRACKS),
            "candidate_onboarded": status["onboarded"],
            "ready_for_agents": status["ready_for_agents"],
            "onboarding_url": f"{base}/onboarding",
            "inbox": "/api/messages",
            "well_known": "/.well-known/agent-card.json",
        }
    return card


def _part_kind(part: dict[str, Any]) -> str:
    return str(part.get("kind") or part.get("type") or "").strip().lower()


def _extract_text(message: dict[str, Any]) -> str:
    parts = message.get("parts") or []
    chunks: list[str] = []
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            if _part_kind(part) in {"text", "text/plain"}:
                text = str(part.get("text") or "").strip()
                if text:
                    chunks.append(text)
    if chunks:
        return "\n".join(chunks)
    return str(message.get("body") or message.get("text") or "").strip()


def _extract_data(message: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    meta = message.get("metadata")
    if isinstance(meta, dict):
        merged.update(meta)
    parts = message.get("parts") or []
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict) and _part_kind(part) == "data" and isinstance(part.get("data"), dict):
                merged.update(part["data"])
    return merged


def _skill_to_track(skill_id: str | None, default: str | None) -> str | None:
    raw = (skill_id or "").strip().lower()
    mapping = {
        "hub.discovery": "discovery",
        "discovery": "discovery",
        "hub.application": "application",
        "hub.apply": "application",
        "application": "application",
        "apply": "application",
        "hub.outreach": "outreach",
        "outreach": "outreach",
        "hub.maintenance": "maintenance",
        "maintenance": "maintenance",
        "maintainer": "maintenance",
        "hub.handoff": None,
    }
    if raw in mapping:
        return mapping[raw] or default
    return canonical_track(raw) or default


def _message_type(data: dict[str, Any]) -> str:
    raw = str(data.get("type") or data.get("kind") or "note").strip().lower()
    if raw in MESSAGE_TYPES:
        return raw
    return "note"


def _http_fetch_json(url: str, *, method: str = "GET", body: dict[str, Any] | None = None, bearer: str | None = None) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"peer HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"peer unreachable: {exc.reason}") from exc
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="peer returned non-JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="peer JSON must be an object")
    return parsed


def create_a2a_router(
    settings: Settings,
    principal_dep: Callable[..., Any],
    optional_principal_dep: Callable[..., Any],
) -> APIRouter:
    router = APIRouter(tags=["a2a"])

    def _card(track: str | None = None, extended: bool = False) -> dict[str, Any]:
        return agent_card(settings, track=track, extended=extended)

    @router.get("/.well-known/agent-card.json")
    @router.get("/.well-known/agent.json")
    @router.get("/a2a/agent-card.json")
    def well_known_card() -> dict[str, Any]:
        return _card()

    @router.get("/a2a/{track}/agent-card.json")
    @router.get("/a2a/{track}/.well-known/agent-card.json")
    def track_card(track: str) -> dict[str, Any]:
        key = canonical_track(track)
        if not key:
            raise HTTPException(status_code=404, detail="unknown track")
        return _card(track=key)

    @router.get("/a2a")
    def a2a_info() -> dict[str, Any]:
        return {
            "protocol": "A2A",
            "protocolVersion": PROTOCOL_VERSION,
            "jsonrpc": "/a2a",
            "agent_card": "/.well-known/agent-card.json",
            "tracks": {t: f"/a2a/{t}/agent-card.json" for t in TRACKS},
        }

    def _handle_rpc(
        payload: dict[str, Any],
        *,
        request: Request,
        principal: Principal | None,
        default_track: str | None,
    ) -> dict[str, Any]:
        rpc_id = payload.get("id")
        if payload.get("jsonrpc") != JSONRPC_VERSION:
            return _jsonrpc_error(rpc_id, RPC_INVALID_REQUEST, "jsonrpc must be 2.0")
        method = str(payload.get("method") or "")
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        db: BoardDB = request.app.state.db

        if method == "agent/getAuthenticatedExtendedCard":
            if principal is None:
                return _jsonrpc_error(rpc_id, RPC_AUTH_REQUIRED, "Authorization Bearer required")
            return _jsonrpc_result(rpc_id, _card(track=default_track, extended=True))

        if method == "tasks/get":
            if principal is None:
                return _jsonrpc_error(rpc_id, RPC_AUTH_REQUIRED, "Authorization Bearer required")
            task_id = str(params.get("id") or params.get("taskId") or "").strip()
            if not task_id:
                return _jsonrpc_error(rpc_id, RPC_INVALID_PARAMS, "id is required")
            stored = get_task(db, task_id, tenant=principal)
            if stored is None:
                return _jsonrpc_error(rpc_id, RPC_TASK_NOT_FOUND, "task not found")
            result = stored.get("result") or {}
            if result:
                return _jsonrpc_result(rpc_id, result)
            return _jsonrpc_result(
                rpc_id,
                _task_object(
                    task_id=stored["id"],
                    context_id=stored["context_id"],
                    state=stored["state"],
                    timestamp=stored["updated_at"],
                ),
            )

        if method == "tasks/cancel":
            if principal is None:
                return _jsonrpc_error(rpc_id, RPC_AUTH_REQUIRED, "Authorization Bearer required")
            task_id = str(params.get("id") or params.get("taskId") or "").strip()
            stored = get_task(db, task_id, tenant=principal) if task_id else None
            if stored is None:
                return _jsonrpc_error(rpc_id, RPC_TASK_NOT_FOUND, "task not found")
            if stored["state"] in {"completed", "canceled", "failed", "rejected"}:
                return _jsonrpc_error(rpc_id, RPC_TASK_NOT_CANCELABLE, "task is not cancelable")
            msg = _agent_message("canceled")
            task = _task_object(
                task_id=stored["id"],
                context_id=stored["context_id"],
                state="canceled",
                message=msg,
                timestamp=stored["updated_at"],
            )
            update_task(db, stored["id"], state="canceled", result=task, tenant=principal)
            return _jsonrpc_result(rpc_id, task)

        if method == "tasks/list":
            if principal is None:
                return _jsonrpc_error(rpc_id, RPC_AUTH_REQUIRED, "Authorization Bearer required")
            rows = list_tasks(db, limit=int(params.get("limit") or 50), tenant=principal)
            return _jsonrpc_result(
                rpc_id,
                {
                    "tasks": [
                        row.get("result")
                        or _task_object(
                            task_id=row["id"],
                            context_id=row["context_id"],
                            state=row["state"],
                        )
                        for row in rows
                    ]
                },
            )

        if method in {"message/stream", "tasks/resubscribe"}:
            return _jsonrpc_error(rpc_id, RPC_METHOD_NOT_FOUND, "streaming is not enabled; use message/send")

        if method != "message/send":
            return _jsonrpc_error(rpc_id, RPC_METHOD_NOT_FOUND, f"unknown method {method}")

        if not candidate_onboarded(settings, db, tenant=principal.tenant if principal else None):
            return _jsonrpc_error(
                rpc_id,
                RPC_CANDIDATE_REQUIRED,
                "Onboard the candidate profile before A2A sends",
                {"onboarding_url": "/onboarding"},
            )
        if principal is None:
            msg = _agent_message("Send Authorization: Bearer $HUB_KEY (owner or agent key).")
            stored = insert_task(db, state="auth-required", request=params)
            task = _task_object(
                task_id=stored["id"],
                context_id=stored["context_id"],
                state="auth-required",
                message=msg,
                timestamp=stored["created_at"],
            )
            update_task(db, stored["id"], result=task)
            return _jsonrpc_result(rpc_id, task)

        message = params.get("message") if isinstance(params.get("message"), dict) else {}
        incoming_text = _extract_text(message)
        data = _extract_data(message)
        if not incoming_text:
            incoming_text = str(data.get("body") or "").strip()
        if not incoming_text:
            return _jsonrpc_error(rpc_id, RPC_INVALID_PARAMS, "message text is required")

        skill_id = str(data.get("skill_id") or data.get("skill") or params.get("skill") or "").strip() or None
        to_track = data.get("to_track") or data.get("track")
        if isinstance(to_track, str):
            to_track = canonical_track(to_track) or to_track
        else:
            to_track = _skill_to_track(skill_id, default_track)
        to_user_id = str(data.get("to_user_id") or "").strip() or None
        job_id = str(data.get("job_id") or "").strip() or None
        msg_type = _message_type(data)
        if not to_user_id and not to_track:
            to_track = default_track or principal.track or "application"
        if to_user_id and to_track:
            to_track = None
        if to_track == "admin" or to_user_id:
            pass
        elif to_track not in {*TRACKS, "admin"}:
            return _jsonrpc_error(rpc_id, RPC_INVALID_PARAMS, "to_track must be a Hub track or admin")

        stored_msg = insert_message(
            db,
            from_user_id=sender_id(principal),
            to_user_id=to_user_id,
            to_track=to_track,
            job_id=job_id,
            msg_type=msg_type,
            body=incoming_text,
            principal=principal,
        )
        db.add_event(
            principal.tenant,
            job_id=job_id,
            actor_role=principal.role,
            actor=principal.actor,
            action="a2a_message_send",
            note=f"{msg_type} via A2A to {to_user_id or to_track}",
            fields={
                "message_id": stored_msg["id"],
                "type": msg_type,
                "to_user_id": to_user_id,
                "to_track": to_track,
                "skill_id": skill_id,
            },
        )
        reply_data = {
            "hub_message_id": stored_msg["id"],
            "type": msg_type,
            "to_track": to_track,
            "to_user_id": to_user_id,
            "job_id": job_id,
        }
        reply = _agent_message(
            f"Hub accepted {msg_type} for {to_user_id or to_track}.",
            reply_data,
        )
        history = [message, reply]
        context_id = str(message.get("contextId") or message.get("context_id") or "") or None
        stored = insert_task(
            db,
            context_id=context_id,
            state="completed",
            skill_id=skill_id or HANDOFF_SKILL["id"],
            from_user_id=principal.user_id,
            message_id=stored_msg["id"],
            request=params,
            tenant=principal,
        )
        artifact = {
            "artifactId": stored_msg["id"],
            "name": "hub-inbox",
            "parts": [_data_part({"message": stored_msg})],
        }
        task = _task_object(
            task_id=stored["id"],
            context_id=stored["context_id"],
            state="completed",
            message=reply,
            history=history,
            artifacts=[artifact],
            metadata={"protocol": "A2A", "hub": "job-apply-os"},
            timestamp=stored["created_at"],
        )
        update_task(db, stored["id"], result=task, tenant=principal)
        return _jsonrpc_result(rpc_id, task)

    @router.post("/a2a")
    async def a2a_rpc(
        request: Request,
        principal: Principal | None = Depends(optional_principal_dep),
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(_jsonrpc_error(None, RPC_PARSE, "parse error"))
        if not isinstance(payload, dict):
            return JSONResponse(_jsonrpc_error(None, RPC_INVALID_REQUEST, "request must be an object"))
        return JSONResponse(_handle_rpc(payload, request=request, principal=principal, default_track=None))

    @router.post("/a2a/{track}")
    async def a2a_track_rpc(
        track: str,
        request: Request,
        principal: Principal | None = Depends(optional_principal_dep),
    ) -> JSONResponse:
        key = canonical_track(track)
        if not key:
            raise HTTPException(status_code=404, detail="unknown track")
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(_jsonrpc_error(None, RPC_PARSE, "parse error"))
        if not isinstance(payload, dict):
            return JSONResponse(_jsonrpc_error(None, RPC_INVALID_REQUEST, "request must be an object"))
        return JSONResponse(_handle_rpc(payload, request=request, principal=principal, default_track=key))

    @router.get("/api/a2a/directory")
    def a2a_directory(
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        base = public_base(settings).rstrip("/")
        db: BoardDB = request.app.state.db
        local = [
            {
                "id": "hub",
                "name": "Job Hub",
                "track": None,
                "card_url": f"{base}/.well-known/agent-card.json",
                "agent_url": f"{base}/a2a",
            },
            *[
                {
                    "id": f"hub-{t}",
                    "name": f"Job Hub / {t}",
                    "track": t,
                    "card_url": f"{base}/a2a/{t}/agent-card.json",
                    "agent_url": f"{base}/a2a/{t}",
                }
                for t in TRACKS
            ],
        ]
        return {"local": local, "peers": list_peers(db, tenant=principal), "protocolVersion": PROTOCOL_VERSION}

    @router.get("/api/a2a/peers")
    def a2a_list_peers(
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        db: BoardDB = request.app.state.db
        return {"peers": list_peers(db, tenant=principal)}

    @router.post("/api/a2a/peers", status_code=201)
    def a2a_add_peer(
        body: PeerIn,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        if principal.role not in {"admin", "maintenance"} and principal.kind != "admin":
            raise HTTPException(status_code=403, detail="only admin or maintenance can register A2A peers")
        db: BoardDB = request.app.state.db
        existing = get_peer_by_card_url(db, body.card_url.strip(), tenant=principal)
        if existing:
            return {"peer": existing, "deduped": True}
        card = _http_fetch_json(body.card_url.strip())
        name = body.name or str(card.get("name") or "peer")
        agent_url = str(card.get("url") or "").strip() or None
        stored = insert_peer(
            db,
            name=name,
            card_url=body.card_url.strip(),
            agent_url=agent_url,
            card=card,
            tenant=principal,
        )
        db.add_event(
            principal.tenant,
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="a2a_peer_add",
            note=name,
            fields={"peer_id": stored["id"], "card_url": stored["card_url"]},
        )
        return {"peer": stored, "deduped": False}

    @router.post("/api/a2a/peers/{peer_id}/send")
    def a2a_send_peer(
        peer_id: str,
        body: PeerSendIn,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        db: BoardDB = request.app.state.db
        peer = get_peer(db, peer_id, tenant=principal)
        if peer is None:
            raise HTTPException(status_code=404, detail="peer not found")
        agent_url = peer.get("agent_url") or ""
        if not agent_url:
            raise HTTPException(status_code=422, detail="peer Agent Card has no url")
        text = (body.text or "").strip()
        message = body.message or {
            "kind": "message",
            "role": "user",
            "messageId": str(uuid4()),
            "parts": [_text_part(text or f"Hub ping from {principal.actor}")],
            "metadata": body.metadata or {"skill_id": body.skill_id},
        }
        rpc = {
            "jsonrpc": JSONRPC_VERSION,
            "id": secrets.token_hex(8),
            "method": "message/send",
            "params": {"message": message},
        }
        reply = _http_fetch_json(agent_url, method="POST", body=rpc)
        touch_peer(db, peer_id, tenant=principal)
        db.add_event(
            principal.tenant,
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="a2a_peer_send",
            note=peer.get("name") or peer_id,
            fields={"peer_id": peer_id},
        )
        return {"peer": {"id": peer_id, "name": peer.get("name")}, "rpc": reply}

    return router
