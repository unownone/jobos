"""A2A tasks and federated peer Agent Cards. SQL lives in app.storage.repos.a2a."""

from __future__ import annotations

from typing import Any, Protocol

from app.storage.repos.a2a import (
    PEER_LIST_DEFAULT_LIMIT,
    SCHEMA,
    TASK_STATES,
    A2ARepo,
    ensure_a2a_schema,
)

__all__ = [
    "PEER_LIST_DEFAULT_LIMIT",
    "SCHEMA",
    "TASK_STATES",
    "ensure_a2a_schema",
    "get_peer",
    "get_peer_by_card_url",
    "get_task",
    "insert_peer",
    "insert_task",
    "list_peers",
    "list_tasks",
    "touch_peer",
    "update_task",
]


class HasConn(Protocol):
    conn: Any

    def commit(self) -> None: ...


def insert_task(
    db: HasConn,
    *,
    context_id: str | None = None,
    state: str = "submitted",
    skill_id: str | None = None,
    from_user_id: str | None = None,
    message_id: str | None = None,
    request: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    task_id: str | None = None,
    tenant: Any | None = None,
) -> dict[str, Any]:
    return A2ARepo(db).insert_task(
        context_id=context_id,
        state=state,
        skill_id=skill_id,
        from_user_id=from_user_id,
        message_id=message_id,
        request=request,
        result=result,
        task_id=task_id,
        tenant=tenant,
    )


def update_task(
    db: HasConn,
    task_id: str,
    *,
    state: str | None = None,
    result: dict[str, Any] | None = None,
    message_id: str | None = None,
    tenant: Any | None = None,
) -> dict[str, Any] | None:
    return A2ARepo(db).update_task(
        task_id,
        state=state,
        result=result,
        message_id=message_id,
        tenant=tenant,
    )


def get_task(db: HasConn, task_id: str, *, tenant: Any | None = None) -> dict[str, Any] | None:
    return A2ARepo(db).get_task(task_id, tenant=tenant)


def list_tasks(
    db: HasConn, *, limit: int = 50, state: str | None = None, tenant: Any | None = None
) -> list[dict[str, Any]]:
    return A2ARepo(db).list_tasks(limit=limit, state=state, tenant=tenant)


def insert_peer(
    db: HasConn,
    *,
    name: str,
    card_url: str,
    agent_url: str | None,
    card: dict[str, Any],
    tenant: Any | None = None,
) -> dict[str, Any]:
    return A2ARepo(db).insert_peer(
        name=name,
        card_url=card_url,
        agent_url=agent_url,
        card=card,
        tenant=tenant,
    )


def get_peer(db: HasConn, peer_id: str, *, tenant: Any | None = None) -> dict[str, Any] | None:
    return A2ARepo(db).get_peer(peer_id, tenant=tenant)


def get_peer_by_card_url(
    db: HasConn, card_url: str, *, tenant: Any | None = None
) -> dict[str, Any] | None:
    return A2ARepo(db).get_peer_by_card_url(card_url, tenant=tenant)


def list_peers(
    db: HasConn, *, tenant: Any | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    return A2ARepo(db).list_peers(
        tenant=tenant, limit=limit if limit is not None else PEER_LIST_DEFAULT_LIMIT
    )


def touch_peer(db: HasConn, peer_id: str, *, tenant: Any | None = None) -> None:
    A2ARepo(db).touch_peer(peer_id, tenant=tenant)
