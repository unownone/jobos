"""QueueBus Seam: tenant routing keys and Memory Adapter isolation."""

from __future__ import annotations

from app.queue_bus import MemoryQueueBus, routing_key, tenant_queue_name
from app.tenant import TenantContext


def test_queue_bus_namespace() -> None:
    bus = MemoryQueueBus()
    a = TenantContext("acc_qa")
    b = TenantContext("acc_qb")
    bus.publish(a, "discovery.search", {"q": "a"})
    bus.publish(b, "discovery.search", {"q": "b"})
    msg_a = bus.get(a)
    msg_b = bus.get(b)
    assert msg_a is not None and msg_b is not None
    assert msg_a.tenant_id == "acc_qa"
    assert msg_b.tenant_id == "acc_qb"
    assert routing_key(a, "discovery.search") == "acc_qa.discovery.search"
    assert tenant_queue_name(a) == "jobos.t.acc_qa"
    assert bus.get(a) is None
    bus.ack(msg_a.delivery_id)
    bus.nack(msg_b.delivery_id, requeue=True)
    again = bus.get(b)
    assert again is not None
    assert again.tenant_id == "acc_qb"
