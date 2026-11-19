"""SQL work queue and in-memory message queue.

Claim is one UPDATE. These tests call it twice in sequence on one connection.
SqliteDatabase keeps check_same_thread=True, so sharing that connection across
threads is not a valid probe and the adapter is left unchanged. The predicate
still has to skip an unexpired claimed row without a select-then-update.

The message-body limit is the UTF-8 length of compact JSON
(``separators=(",", ":")``, ``ensure_ascii=False``). A body larger than 128 KiB
is refused.
"""

from __future__ import annotations

import json

import pytest

from app.storage.message_queue import InlineQueue, PayloadTooLarge
from app.storage.sqlite import SqliteDatabase
from app.storage.work_queue import Conflict, NotFound, SqlWorkQueue, TooManyKinds

ACCOUNT = "acct_1"
OTHER = "acct_2"
KIND = "discovery.search"
NOW = "2020-01-01T00:00:00Z"
LEASE = "2020-01-01T00:15:00Z"
EXPIRED = "2020-01-01T00:15:01Z"
BODY_LIMIT = 128 * 1024


def _nbytes(body: dict) -> int:
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return len(encoded)


def fresh() -> tuple[SqliteDatabase, SqlWorkQueue]:
    db = SqliteDatabase(":memory:")
    db.execute(
        """
        CREATE TABLE queue_items (
            id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            track TEXT,
            job_id TEXT,
            payload_json TEXT,
            status TEXT NOT NULL,
            claimed_by TEXT,
            lease_until TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            dedupe_key TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE UNIQUE INDEX idx_queue_account_dedupe
            ON queue_items(account_id, dedupe_key)
        """
    )
    return db, SqlWorkQueue(db)


def push(
    queue: SqlWorkQueue,
    *,
    item_id: str,
    dedupe_key: str,
    kind: str = KIND,
    account_id: str = ACCOUNT,
    now: str = NOW,
    payload: dict | None = None,
    track: str | None = "discovery",
    job_id: str | None = None,
):
    return queue.push(
        account_id=account_id,
        kind=kind,
        dedupe_key=dedupe_key,
        payload=payload if payload is not None else {"portal": "example"},
        track=track,
        job_id=job_id,
        now=now,
        item_id=item_id,
    )


def test_duplicate_push_returns_the_same_row_and_does_not_insert_another() -> None:
    db, queue = fresh()
    first = queue.push(
        account_id=ACCOUNT,
        kind=KIND,
        dedupe_key="same",
        payload={"n": 1},
        track="discovery",
        job_id="job_1",
        now=NOW,
        item_id="qi_1",
    )
    second = queue.push(
        account_id=ACCOUNT,
        kind=KIND,
        dedupe_key="same",
        payload={"n": 2},
        track="apply",
        job_id="job_2",
        now="2020-01-02T00:00:00Z",
        item_id="qi_2",
    )
    assert first.deduped is False
    assert second.deduped is True
    assert second.item == first.item
    assert second.item.id == "qi_1"
    assert second.item.payload == {"n": 1}
    assert second.item.created_at == NOW
    assert db.fetch_one("SELECT COUNT(*) AS c FROM queue_items")["c"] == 1


def test_dedupe_key_is_scoped_to_the_account() -> None:
    db, queue = fresh()
    first = push(queue, item_id="qi_1", dedupe_key="same")
    second = push(queue, item_id="qi_2", dedupe_key="same", account_id=OTHER)
    assert first.deduped is False
    assert second.deduped is False
    assert first.item.id == "qi_1"
    assert second.item.id == "qi_2"
    assert db.fetch_one("SELECT COUNT(*) AS c FROM queue_items")["c"] == 2


def test_claim_returns_the_oldest_open_item() -> None:
    _, queue = fresh()
    push(queue, item_id="qi_b", dedupe_key="b")
    push(queue, item_id="qi_a", dedupe_key="a")
    claimed = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-a", now=NOW)
    assert claimed is not None
    assert claimed.id == "qi_a"
    assert claimed.status == "claimed"
    assert claimed.claimed_by == "worker-a"
    assert claimed.lease_until == LEASE


def test_second_claim_does_not_return_the_same_unexpired_item() -> None:
    _, queue = fresh()
    push(queue, item_id="qi_1", dedupe_key="only")
    first = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-a", now=NOW)
    second = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-b", now=NOW)
    assert first is not None
    assert first.id == "qi_1"
    assert second is None


def test_claim_uses_one_statement() -> None:
    db, queue = fresh()
    push(queue, item_id="qi_a", dedupe_key="a")
    push(queue, item_id="qi_b", dedupe_key="b")
    db.queries.reset()
    first = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-a", now=NOW)
    assert first is not None and first.id == "qi_a"
    assert db.queries.count == 1
    db.queries.reset()
    second = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-b", now=NOW)
    assert second is not None and second.id == "qi_b"
    assert db.queries.count == 1
    db.queries.reset()
    assert queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-c", now=NOW) is None
    assert db.queries.count == 1


def test_expired_lease_can_be_claimed_by_someone_else() -> None:
    _, queue = fresh()
    push(queue, item_id="qi_1", dedupe_key="only")
    first = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-a", now=NOW)
    assert first is not None
    assert first.lease_until == LEASE
    still_held = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-b", now=LEASE)
    assert still_held is None
    stolen = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-b", now=EXPIRED)
    assert stolen is not None
    assert stolen.id == "qi_1"
    assert stolen.status == "claimed"
    assert stolen.claimed_by == "worker-b"
    assert stolen.lease_until == "2020-01-01T00:30:01Z"


def test_claim_binds_kinds_and_rejects_more_than_20() -> None:
    db, queue = fresh()
    push(queue, item_id="qi_0", dedupe_key="other", kind="other")
    push(queue, item_id="qi_1", dedupe_key="search")
    malicious = "discovery.search') OR '1'='1"
    assert queue.claim(account_id=ACCOUNT, kinds=[malicious], claimant="worker-a", now=NOW) is None
    kinds = [f"k{i}" for i in range(20)]
    kinds[3] = KIND
    claimed = queue.claim(account_id=ACCOUNT, kinds=kinds, claimant="worker-a", now=NOW)
    assert claimed is not None
    assert claimed.id == "qi_1"
    db.queries.reset()
    with pytest.raises(TooManyKinds):
        queue.claim(
            account_id=ACCOUNT,
            kinds=[f"k{i}" for i in range(21)],
            claimant="worker-a",
            now=NOW,
        )
    assert db.queries.count == 0


def test_claim_with_no_kinds_returns_nothing() -> None:
    db, queue = fresh()
    push(queue, item_id="qi_1", dedupe_key="only")
    db.queries.reset()
    assert queue.claim(account_id=ACCOUNT, kinds=[], claimant="worker-a", now=NOW) is None
    assert db.queries.count == 0


def test_ack_by_claimant_succeeds_and_other_claimant_conflicts() -> None:
    _, queue = fresh()
    push(queue, item_id="qi_1", dedupe_key="only")
    claimed = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-a", now=NOW)
    assert claimed is not None
    with pytest.raises(Conflict):
        queue.ack(account_id=ACCOUNT, item_id=claimed.id, claimant="worker-b", now=NOW)
    acked = queue.ack(account_id=ACCOUNT, item_id=claimed.id, claimant="worker-a", now=NOW)
    assert acked.status == "acked"
    assert acked.lease_until is None
    assert acked.claimed_by == "worker-a"
    assert queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-b", now=NOW) is None


def test_admin_can_ack_another_claimants_item() -> None:
    _, queue = fresh()
    push(queue, item_id="qi_1", dedupe_key="only")
    claimed = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-a", now=NOW)
    assert claimed is not None
    acked = queue.ack(
        account_id=ACCOUNT,
        item_id=claimed.id,
        claimant="admin-user",
        now=NOW,
        admin=True,
    )
    assert acked.status == "acked"
    assert acked.claimed_by == "worker-a"


def test_ack_conflicts_when_the_lease_is_expired() -> None:
    _, queue = fresh()
    push(queue, item_id="qi_1", dedupe_key="only")
    claimed = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-a", now=NOW)
    assert claimed is not None
    with pytest.raises(Conflict):
        queue.ack(account_id=ACCOUNT, item_id=claimed.id, claimant="worker-a", now=EXPIRED)
    with pytest.raises(Conflict):
        queue.ack(
            account_id=ACCOUNT,
            item_id=claimed.id,
            claimant="admin-user",
            now=EXPIRED,
            admin=True,
        )


def test_ack_succeeds_at_the_lease_instant() -> None:
    _, queue = fresh()
    push(queue, item_id="qi_1", dedupe_key="only")
    claimed = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-a", now=NOW)
    assert claimed is not None
    acked = queue.ack(account_id=ACCOUNT, item_id=claimed.id, claimant="worker-a", now=LEASE)
    assert acked.status == "acked"


def test_missing_ack_is_not_found() -> None:
    _, queue = fresh()
    with pytest.raises(NotFound):
        queue.ack(account_id=ACCOUNT, item_id="missing", claimant="worker-a", now=NOW)


def test_nack_requeues_until_attempt_5_then_dead() -> None:
    _, queue = fresh()
    push(queue, item_id="qi_1", dedupe_key="only")
    item = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-a", now=NOW)
    assert item is not None
    for attempt in range(1, 5):
        item = queue.nack(
            account_id=ACCOUNT,
            item_id=item.id,
            claimant="worker-a",
            now=NOW,
            requeue=True,
        )
        assert item.status == "open"
        assert item.attempts == attempt
        assert item.claimed_by is None
        assert item.lease_until is None
        claimed = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-a", now=NOW)
        assert claimed is not None
        assert claimed.id == "qi_1"
        assert claimed.attempts == attempt
        item = claimed
    dead = queue.nack(
        account_id=ACCOUNT,
        item_id=item.id,
        claimant="worker-a",
        now=NOW,
        requeue=True,
    )
    assert dead.attempts == 5
    assert dead.status == "dead"
    assert dead.lease_until is None
    assert dead.claimed_by == "worker-a"
    assert queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-b", now=NOW) is None


def test_nack_without_requeue_is_dead_on_the_first_attempt() -> None:
    _, queue = fresh()
    push(queue, item_id="qi_1", dedupe_key="only")
    claimed = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-a", now=NOW)
    assert claimed is not None
    dead = queue.nack(
        account_id=ACCOUNT,
        item_id=claimed.id,
        claimant="worker-a",
        now=NOW,
        requeue=False,
    )
    assert dead.status == "dead"
    assert dead.attempts == 1
    assert dead.claimed_by == "worker-a"
    assert queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-b", now=NOW) is None


def test_nack_by_someone_else_conflicts() -> None:
    _, queue = fresh()
    push(queue, item_id="qi_1", dedupe_key="only")
    claimed = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-a", now=NOW)
    assert claimed is not None
    with pytest.raises(Conflict):
        queue.nack(account_id=ACCOUNT, item_id=claimed.id, claimant="worker-b", now=NOW)
    extended = queue.extend(account_id=ACCOUNT, item_id=claimed.id, claimant="worker-a", now=NOW)
    assert extended.status == "claimed"
    assert extended.attempts == 0


def test_extend_moves_lease_until_forward() -> None:
    _, queue = fresh()
    push(queue, item_id="qi_1", dedupe_key="only")
    claimed = queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-a", now=NOW)
    assert claimed is not None
    assert claimed.lease_until == LEASE
    extended = queue.extend(
        account_id=ACCOUNT,
        item_id=claimed.id,
        claimant="worker-a",
        now="2020-01-01T00:10:00Z",
    )
    assert extended.status == "claimed"
    assert extended.claimed_by == "worker-a"
    assert extended.lease_until == "2020-01-01T00:25:00Z"
    with pytest.raises(Conflict):
        queue.extend(
            account_id=ACCOUNT,
            item_id=claimed.id,
            claimant="worker-b",
            now="2020-01-01T00:10:00Z",
        )
    assert (
        queue.claim(account_id=ACCOUNT, kinds=[KIND], claimant="worker-b", now="2020-01-01T00:20:00Z")
        is None
    )


def test_inline_queue_records_messages() -> None:
    queue = InlineQueue()
    queue.send("work.ready", {"job": "1"}, key="acct_1")
    queue.send("work.ready", {"job": "2"})
    assert [(message.topic, message.body, message.key) for message in queue.messages] == [
        ("work.ready", {"job": "1"}, "acct_1"),
        ("work.ready", {"job": "2"}, None),
    ]


def test_inline_queue_refuses_an_oversized_body() -> None:
    queue = InlineQueue()
    room = BODY_LIMIT - _nbytes({"blob": ""})
    accepted = {"blob": "x" * room}
    assert _nbytes(accepted) == BODY_LIMIT
    queue.send("work.ready", accepted, key="ok")
    assert len(queue.messages) == 1
    refused = {"blob": "x" * (room + 1)}
    assert _nbytes(refused) == BODY_LIMIT + 1
    with pytest.raises(PayloadTooLarge):
        queue.send("work.ready", refused)
    assert len(queue.messages) == 1
    assert queue.messages[0].body == accepted


def test_inline_queue_requires_a_dict_body() -> None:
    queue = InlineQueue()
    for body in ("text", ["x"], None, 5):
        with pytest.raises(TypeError):
            queue.send("work.ready", body)  # type: ignore[arg-type]
    assert queue.messages == []
