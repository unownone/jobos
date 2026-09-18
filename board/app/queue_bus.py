"""QueueBus Module: tenant-namespaced publish/get/ack.

The Hub claim/lease Interface stays on QueueService. This Module is the AMQP
Seam inside it: routing keys are `{account_id}.{kind}` so callers never format
tenant topology. Two Adapters: RabbitMqBus (production) and MemoryQueueBus (tests).
"""

from __future__ import annotations

import json
import secrets
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Protocol

from app.tenant import TenantContext

EXCHANGE_NAME = "jobos.work"

try:
    import pika
except ImportError:  # pragma: no cover - production Adapter needs pika installed
    pika = None


def new_delivery_id() -> str:
    return "del_" + secrets.token_urlsafe(12)


def routing_key(tenant: TenantContext, kind: str) -> str:
    return f"{tenant.account_id}.{kind}"


def tenant_queue_name(tenant: TenantContext) -> str:
    return f"jobos.t.{tenant.account_id}"


@dataclass(frozen=True)
class BusMessage:
    tenant_id: str
    routing_key: str
    body: bytes
    delivery_id: str
    kind: str


class QueueBus(Protocol):
    def publish(self, tenant: TenantContext, kind: str, payload: dict[str, Any]) -> None: ...

    def get(self, tenant: TenantContext, kinds: list[str] | None = None) -> BusMessage | None: ...

    def ack(self, delivery_id: str) -> None: ...

    def nack(self, delivery_id: str, *, requeue: bool = True) -> None: ...

    def close(self) -> None: ...


class MemoryQueueBus:
    """In-process Adapter. Tenant isolation is a dict key, not a hope."""

    def __init__(self) -> None:
        self._queues: dict[str, deque[BusMessage]] = defaultdict(deque)
        self._inflight: dict[str, tuple[str, BusMessage]] = {}
        self._lock = threading.Lock()

    def publish(self, tenant: TenantContext, kind: str, payload: dict[str, Any]) -> None:
        msg = BusMessage(
            tenant_id=tenant.account_id,
            routing_key=routing_key(tenant, kind),
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            delivery_id=new_delivery_id(),
            kind=kind,
        )
        with self._lock:
            self._queues[tenant.account_id].append(msg)

    def get(self, tenant: TenantContext, kinds: list[str] | None = None) -> BusMessage | None:
        allowed = set(kinds) if kinds else None
        with self._lock:
            q = self._queues[tenant.account_id]
            kept: deque[BusMessage] = deque()
            found: BusMessage | None = None
            while q:
                msg = q.popleft()
                if allowed is None or msg.kind in allowed:
                    found = msg
                    break
                kept.append(msg)
            while q:
                kept.append(q.popleft())
            self._queues[tenant.account_id] = kept
            if found is None:
                return None
            self._inflight[found.delivery_id] = (tenant.account_id, found)
            return found

    def ack(self, delivery_id: str) -> None:
        with self._lock:
            self._inflight.pop(delivery_id, None)

    def nack(self, delivery_id: str, *, requeue: bool = True) -> None:
        with self._lock:
            item = self._inflight.pop(delivery_id, None)
            if item and requeue:
                account_id, msg = item
                self._queues[account_id].appendleft(msg)

    def close(self) -> None:
        with self._lock:
            self._queues.clear()
            self._inflight.clear()


class RabbitMqBus:
    """AMQP Adapter. Per-tenant queue `jobos.t.{account_id}` bound to `{account_id}.*`."""

    def __init__(self, amqp_url: str) -> None:
        if pika is None:
            raise RuntimeError("pika is required for QUEUE_ADAPTER=rabbitmq")
        self._url = amqp_url
        self._params = pika.URLParameters(amqp_url)
        self._lock = threading.Lock()
        self._conn = None
        self._channel = None
        self._connect()

    def _connect(self) -> None:
        self._conn = pika.BlockingConnection(self._params)
        self._channel = self._conn.channel()
        self._channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type="topic", durable=True)

    def _ensure(self) -> Any:
        if self._conn is None or self._conn.is_closed:
            self._connect()
        return self._channel

    def _bind_tenant(self, tenant: TenantContext) -> str:
        channel = self._ensure()
        queue = tenant_queue_name(tenant)
        channel.queue_declare(queue=queue, durable=True)
        channel.queue_bind(
            exchange=EXCHANGE_NAME,
            queue=queue,
            routing_key=f"{tenant.account_id}.*",
        )
        return queue

    def publish(self, tenant: TenantContext, kind: str, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        key = routing_key(tenant, kind)
        with self._lock:
            channel = self._ensure()
            self._bind_tenant(tenant)
            channel.basic_publish(
                exchange=EXCHANGE_NAME,
                routing_key=key,
                body=body,
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=2,
                    headers={"account_id": tenant.account_id, "kind": kind},
                ),
            )

    def get(self, tenant: TenantContext, kinds: list[str] | None = None) -> BusMessage | None:
        allowed = set(kinds) if kinds else None
        with self._lock:
            channel = self._ensure()
            queue = self._bind_tenant(tenant)
            # Peek until a matching kind or empty. Non-matching messages requeue.
            skipped: list[Any] = []
            found = None
            tag = None
            while True:
                method, props, body = channel.basic_get(queue=queue, auto_ack=False)
                if method is None:
                    break
                headers = (props.headers or {}) if props else {}
                kind = str(headers.get("kind") or "")
                if not kind and "." in method.routing_key:
                    kind = method.routing_key.split(".", 1)[1]
                if allowed is None or kind in allowed:
                    found = BusMessage(
                        tenant_id=tenant.account_id,
                        routing_key=method.routing_key,
                        body=body or b"",
                        delivery_id=str(method.delivery_tag),
                        kind=kind,
                    )
                    tag = method.delivery_tag
                    break
                skipped.append(method.delivery_tag)
            for skip_tag in skipped:
                channel.basic_nack(delivery_tag=skip_tag, requeue=True)
            if found is None:
                return None
            # Keep unacked until Hub ack/nack maps delivery_id.
            del tag
            return found

    def ack(self, delivery_id: str) -> None:
        with self._lock:
            channel = self._ensure()
            channel.basic_ack(delivery_tag=int(delivery_id))

    def nack(self, delivery_id: str, *, requeue: bool = True) -> None:
        with self._lock:
            channel = self._ensure()
            channel.basic_nack(delivery_tag=int(delivery_id), requeue=requeue)

    def close(self) -> None:
        with self._lock:
            try:
                if self._conn and self._conn.is_open:
                    self._conn.close()
            finally:
                self._conn = None
                self._channel = None


def build_queue_bus(*, amqp_url: str = "", adapter: str = "memory") -> QueueBus:
    mode = (adapter or "memory").strip().lower()
    if mode in {"rabbitmq", "amqp", "rabbit"} and amqp_url:
        return RabbitMqBus(amqp_url)
    if mode in {"rabbitmq", "amqp", "rabbit"} and not amqp_url:
        raise RuntimeError("AMQP_URL is required when QUEUE_ADAPTER=rabbitmq")
    return MemoryQueueBus()
