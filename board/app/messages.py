"""Inter-agent Hub inbox APIs. Not employer email, SMS, WhatsApp, or LinkedIn InMail."""

from __future__ import annotations

from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.auth import Principal
from app.constants import TRACKS, canonical_track
from app.db import BoardDB
from app.message_store import (
    MessageForbidden,
    MessageNotFound,
    count_unread,
    insert_message,
    list_messages,
    mark_read,
    sender_id,
)

MESSAGE_TYPES = ("note", "block", "handoff", "question")
ADMIN_TRACK = "admin"
DESTINATION_TRACKS = (*TRACKS, ADMIN_TRACK)

EMPLOYER_CHANNELS = frozenset(
    {
        "sms",
        "whatsapp",
        "inmail",
        "linkedin",
        "linkedin_dm",
        "email",
        "employer_email",
        "phone",
        "text",
        "mms",
        "imessage",
    }
)


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str | None = None
    kind: str | None = None
    body: str = Field(min_length=1)
    job_id: str | None = None
    to_user_id: str | None = None
    to_track: str | None = None
    to: str | None = None
    channel: str | None = None
    to_email: str | None = None
    email: str | None = None
    phone: str | None = None

    @field_validator("body")
    @classmethod
    def _strip_body(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("body is required")
        return text

    @model_validator(mode="after")
    def _reject_employer_send(self) -> MessageIn:
        for raw in (self.channel, self.type, self.kind, self.to_email, self.email, self.phone):
            if raw is None:
                continue
            key = str(raw).strip().lower()
            if key in EMPLOYER_CHANNELS or "@" in key:
                raise ValueError(
                    "Hub messages are agent-to-agent only; do not send employer email/SMS/WhatsApp/InMail here"
                )
        if self.channel is not None:
            raise ValueError(
                "channel is not supported; Hub inbox is agent-to-agent, not employer outreach"
            )
        if self.to_email or self.email or self.phone:
            raise ValueError("cannot address Hub messages to an email or phone")
        dest = (self.to or self.to_user_id or "").strip()
        if "@" in dest:
            raise ValueError("cannot send to an arbitrary email address via this API")
        return self


class HeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    status_hint: str | None = None
    task_id: str | None = None
    producing: bool | None = None


def _message_type(body: MessageIn) -> str:
    raw = (body.type or body.kind or "").strip().lower()
    if raw not in MESSAGE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"type must be one of {list(MESSAGE_TYPES)} (not employer channels)",
        )
    return raw


def _canon_dest(value: str) -> str:
    lowered = value.strip().lower()
    if lowered == ADMIN_TRACK:
        return ADMIN_TRACK
    return canonical_track(lowered) or lowered


def _resolve_destination(db: BoardDB, body: MessageIn) -> tuple[str | None, str | None]:
    to_user_id = (body.to_user_id or "").strip() or None
    to_track = (body.to_track or "").strip() or None
    raw_to = (body.to or "").strip() or None

    if raw_to:
        if raw_to.lower() == ADMIN_TRACK or canonical_track(raw_to) in TRACKS:
            if to_track and _canon_dest(to_track) != _canon_dest(raw_to):
                raise HTTPException(status_code=422, detail="to and to_track disagree")
            to_track = raw_to
        elif raw_to.startswith("usr_") or db.get_user(raw_to):
            if to_user_id and to_user_id != raw_to:
                raise HTTPException(status_code=422, detail="to and to_user_id disagree")
            to_user_id = raw_to
        elif "@" in raw_to:
            raise HTTPException(
                status_code=422,
                detail="cannot send to an arbitrary email address via this API",
            )
        else:
            raise HTTPException(
                status_code=422,
                detail="to must be a hub user id, a track, or admin",
            )

    if to_user_id and to_track:
        raise HTTPException(
            status_code=422,
            detail="choose one destination: to_user_id, to_track, or admin",
        )
    if not to_user_id and not to_track:
        raise HTTPException(
            status_code=422,
            detail="destination required: to_user_id, to_track, or to=admin",
        )

    if to_track:
        dest = _canon_dest(to_track)
        if dest not in DESTINATION_TRACKS:
            raise HTTPException(
                status_code=422,
                detail="to_track must be discovery|application|outreach|maintenance|admin",
            )
        to_track = dest

    if to_user_id:
        if to_user_id.startswith("compat:"):
            raise HTTPException(status_code=422, detail="cannot target a compat sentinel")
        user = db.get_user(to_user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="recipient user not found")
        if user.get("disabled_at"):
            raise HTTPException(status_code=422, detail="recipient user is disabled")

    return to_user_id, to_track


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def create_messages_router(principal_dep: Callable[..., Any]) -> APIRouter:
    router = APIRouter(tags=["messages"])

    @router.post("/api/messages", status_code=201)
    def send_message(
        body: MessageIn,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        db: BoardDB = request.app.state.db
        msg_type = _message_type(body)
        to_user_id, to_track = _resolve_destination(db, body)
        stored = insert_message(
            db,
            from_user_id=sender_id(principal),
            to_user_id=to_user_id,
            to_track=to_track,
            job_id=body.job_id,
            msg_type=msg_type,
            body=body.body,
        )
        db.add_event(
            job_id=body.job_id,
            actor_role=principal.role,
            actor=principal.actor,
            action="message_send",
            note=f"{msg_type} to {to_user_id or to_track}",
            fields={
                "message_id": stored["id"],
                "type": msg_type,
                "to_user_id": to_user_id,
                "to_track": to_track,
            },
        )
        return {
            "message": stored,
            "pending_messages": count_unread(db, principal),
        }

    @router.get("/api/messages")
    def pull_messages(
        request: Request,
        principal: Principal = Depends(principal_dep),
        unread: Annotated[str | None, Query()] = None,
        job_id: str | None = None,
        type: Annotated[str | None, Query(alias="type")] = None,
        sent: Annotated[str | None, Query()] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        db: BoardDB = request.app.state.db
        msg_type = (type or "").strip().lower() or None
        if msg_type and msg_type not in MESSAGE_TYPES:
            raise HTTPException(status_code=422, detail=f"type must be one of {list(MESSAGE_TYPES)}")
        messages = list_messages(
            db,
            principal,
            unread=_truthy(unread),
            job_id=job_id,
            msg_type=msg_type,
            sent=_truthy(sent),
            limit=limit,
        )
        return {
            "messages": messages,
            "count": len(messages),
            "pending_messages": count_unread(db, principal),
            "types": list(MESSAGE_TYPES),
        }

    @router.post("/api/messages/{message_id}/read")
    def read_message(
        message_id: str,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        db: BoardDB = request.app.state.db
        try:
            stored = mark_read(db, principal, message_id)
        except MessageNotFound as exc:
            raise HTTPException(status_code=404, detail="message not found") from exc
        except MessageForbidden as exc:
            raise HTTPException(status_code=403, detail="not a recipient of this message") from exc
        db.add_event(
            job_id=stored.get("job_id"),
            actor_role=principal.role,
            actor=principal.actor,
            action="message_read",
            note="read receipt",
            fields={"message_id": message_id},
        )
        return {
            "message": stored,
            "pending_messages": count_unread(db, principal),
        }

    @router.post("/api/presence/heartbeat")
    def heartbeat_pending(
        request: Request,
        principal: Principal = Depends(principal_dep),
        body: HeartbeatIn | None = None,
    ) -> dict[str, Any]:
        """Inbox poll hook. Does not persist a presence directory (phase C)."""
        del body
        db: BoardDB = request.app.state.db
        return {
            "ok": True,
            "pending_messages": count_unread(db, principal),
            "heartbeat_s": 10,
        }

    return router
