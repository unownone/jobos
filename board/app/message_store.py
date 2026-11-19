"""Inbox rows. SQL lives in app.storage.repos.messages. The router lives in messages.py."""

from __future__ import annotations

from typing import Any, Protocol

from app.storage.repos.messages import (
    SCHEMA,
    InboxPrincipal,
    MessageForbidden,
    MessageNotFound,
    MessageRepo,
    can_see,
    ensure_messages_schema,
    inbound_where,
    is_hub_admin,
    reader_key,
    row_to_message,
    sender_id,
)

__all__ = [
    "SCHEMA",
    "InboxPrincipal",
    "MessageForbidden",
    "MessageNotFound",
    "MessageRepo",
    "can_see",
    "count_unread",
    "ensure_messages_schema",
    "get_message",
    "inbound_where",
    "insert_message",
    "is_hub_admin",
    "list_messages",
    "mark_read",
    "reader_key",
    "row_to_message",
    "sender_id",
]


class HasConn(Protocol):
    conn: Any

    def commit(self) -> None: ...


def count_unread(db: HasConn, principal: InboxPrincipal) -> int:
    return MessageRepo(db).count_unread(principal)


def list_messages(
    db: HasConn,
    principal: InboxPrincipal,
    *,
    unread: bool = False,
    job_id: str | None = None,
    msg_type: str | None = None,
    sent: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return MessageRepo(db).list_messages(
        principal,
        unread=unread,
        job_id=job_id,
        msg_type=msg_type,
        sent=sent,
        limit=limit,
    )


def insert_message(
    db: HasConn,
    *,
    from_user_id: str,
    to_user_id: str | None,
    to_track: str | None,
    job_id: str | None,
    msg_type: str,
    body: str,
    principal: InboxPrincipal | None = None,
) -> dict[str, Any]:
    return MessageRepo(db).insert_message(
        from_user_id=from_user_id,
        to_user_id=to_user_id,
        to_track=to_track,
        job_id=job_id,
        msg_type=msg_type,
        body=body,
        principal=principal,
    )


def get_message(
    db: HasConn, msg_id: str, *, principal: InboxPrincipal | None = None
) -> dict[str, Any] | None:
    return MessageRepo(db).get_message(msg_id, principal=principal)


def mark_read(db: HasConn, principal: InboxPrincipal, msg_id: str) -> dict[str, Any]:
    return MessageRepo(db).mark_read(principal, msg_id)
