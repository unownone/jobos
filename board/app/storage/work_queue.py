"""Work queue on the Database port.

Statuses are open, claimed, acked, and dead. A claim lasts 15 minutes. The
fifth nack, or any nack with requeue false, marks the row dead. Dedupe is the
unique pair (account_id, dedupe_key).

The caller owns the queue_items table and that unique index. This module does
not talk to QueueService.

Claim is one UPDATE ... WHERE id = (SELECT ... ORDER BY id LIMIT 1) with the
same predicate repeated on the UPDATE, then RETURNING. There is no
select-then-update and no process lock.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Protocol, Sequence

from app.storage.port import Database, Result

LEASE_MINUTES = 15
NACK_DEAD_AFTER = 5
MAX_CLAIM_KINDS = 20


class Conflict(Exception):
    """The row exists, and this transition is not allowed."""


class NotFound(Exception):
    """No queue item with this id belongs to the account."""


class TooManyKinds(ValueError):
    """Claim was given more kinds than the statement budget allows."""

    def __init__(self, count: int) -> None:
        super().__init__(f"claim accepts at most {MAX_CLAIM_KINDS} kinds, got {count}")
        self.count = count


@dataclass(frozen=True)
class QueueItem:
    id: str
    account_id: str
    kind: str
    track: str | None
    job_id: str | None
    payload: dict[str, Any]
    status: str
    claimed_by: str | None
    lease_until: str | None
    attempts: int
    dedupe_key: str
    created_at: str


@dataclass(frozen=True)
class PushResult:
    item: QueueItem
    deduped: bool


class WorkQueue(Protocol):
    def push(
        self,
        *,
        account_id: str,
        kind: str,
        dedupe_key: str,
        now: str,
        payload: dict[str, Any] | None = None,
        track: str | None = None,
        job_id: str | None = None,
        item_id: str | None = None,
    ) -> PushResult:
        """Insert the row, or return the existing one when the dedupe key hits."""

    def claim(
        self,
        *,
        account_id: str,
        kinds: Sequence[str],
        claimant: str,
        now: str,
    ) -> QueueItem | None:
        """Claim the oldest open or expired item for these kinds. One statement."""

    def ack(
        self,
        *,
        account_id: str,
        item_id: str,
        claimant: str,
        now: str,
        admin: bool = False,
    ) -> QueueItem:
        """Ack a live claim. The claimant or an admin may do it."""

    def nack(
        self,
        *,
        account_id: str,
        item_id: str,
        claimant: str,
        now: str,
        requeue: bool = True,
        admin: bool = False,
    ) -> QueueItem:
        """Count an attempt. Requeue until attempt 5, then dead."""

    def extend(
        self,
        *,
        account_id: str,
        item_id: str,
        claimant: str,
        now: str,
    ) -> QueueItem:
        """Move lease_until to now plus 15 minutes for the current claimant."""


def _parse(now: str) -> datetime:
    text = now[:-1] + "+00:00" if now.endswith("Z") else now
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid timestamp {now!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp(now: str) -> str:
    return _format(_parse(now))


def _lease_until(now: str) -> str:
    return _format(_parse(now) + timedelta(minutes=LEASE_MINUTES))


def _new_id() -> str:
    token = secrets.token_urlsafe(16).replace("-", "").replace("_", "")
    return "qi_" + token[:26]


def _bit(value: bool) -> int:
    return 1 if value else 0


def _kinds(kinds: Sequence[str]) -> tuple[str, ...]:
    if isinstance(kinds, (str, bytes)):
        raise TypeError("kinds must be a sequence of strings")
    values = tuple(kinds)
    if len(values) > MAX_CLAIM_KINDS:
        raise TooManyKinds(len(values))
    for kind in values:
        if not isinstance(kind, str):
            raise TypeError("kinds must be a sequence of strings")
    return values


def _payload_json(payload: dict[str, Any] | None) -> str:
    if payload is None:
        body: dict[str, Any] = {}
    elif isinstance(payload, dict):
        body = payload
    else:
        raise TypeError("payload must be a dict")
    return json.dumps(body, ensure_ascii=False)


def _item(row: Mapping[str, Any]) -> QueueItem:
    raw = row["payload_json"]
    if raw:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("queue payload_json must be a JSON object")
        payload = parsed
    else:
        payload = {}
    return QueueItem(
        id=row["id"],
        account_id=row["account_id"],
        kind=row["kind"],
        track=row["track"],
        job_id=row["job_id"],
        payload=payload,
        status=row["status"],
        claimed_by=row["claimed_by"],
        lease_until=row["lease_until"],
        attempts=int(row["attempts"] or 0),
        dedupe_key=row["dedupe_key"],
        created_at=row["created_at"],
    )


def _claim_sql(kind_count: int) -> str:
    placeholders = ",".join("?" for _ in range(kind_count))
    return f"""
        UPDATE queue_items
        SET status = 'claimed', claimed_by = ?, lease_until = ?
        WHERE id = (
            SELECT id FROM queue_items
            WHERE account_id = ?
              AND kind IN ({placeholders})
              AND (
                    status = 'open'
                    OR (
                        status = 'claimed'
                        AND (lease_until IS NULL OR lease_until < ?)
                    )
                  )
            ORDER BY id
            LIMIT 1
        )
        AND (
            status = 'open'
            OR (
                status = 'claimed'
                AND (lease_until IS NULL OR lease_until < ?)
            )
        )
        RETURNING *
    """


class SqlWorkQueue:
    def __init__(self, db: Database) -> None:
        self._db = db

    def push(
        self,
        *,
        account_id: str,
        kind: str,
        dedupe_key: str,
        now: str,
        payload: dict[str, Any] | None = None,
        track: str | None = None,
        job_id: str | None = None,
        item_id: str | None = None,
    ) -> PushResult:
        _parse(now)
        stored_id = item_id or _new_id()
        inserted = self._db.execute(
            """
            INSERT INTO queue_items (
                id, account_id, kind, track, job_id, payload_json, status,
                claimed_by, lease_until, attempts, dedupe_key, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'open', NULL, NULL, 0, ?, ?)
            ON CONFLICT(account_id, dedupe_key) DO NOTHING
            RETURNING *
            """,
            (
                stored_id,
                account_id,
                kind,
                track,
                job_id,
                _payload_json(payload),
                dedupe_key,
                now,
            ),
        )
        if inserted.rows:
            return PushResult(item=_item(inserted.rows[0]), deduped=False)
        existing = self._db.fetch_one(
            """
            SELECT * FROM queue_items
            WHERE account_id = ? AND dedupe_key = ?
            """,
            (account_id, dedupe_key),
        )
        if existing is None:
            raise RuntimeError("queue insert did not persist")
        return PushResult(item=_item(existing), deduped=True)

    def claim(
        self,
        *,
        account_id: str,
        kinds: Sequence[str],
        claimant: str,
        now: str,
    ) -> QueueItem | None:
        selected = _kinds(kinds)
        if not selected:
            return None
        current = _stamp(now)
        until = _lease_until(now)
        result = self._db.execute(
            _claim_sql(len(selected)),
            (claimant, until, account_id, *selected, current, current),
        )
        if not result.rows:
            return None
        return _item(result.rows[0])

    def ack(
        self,
        *,
        account_id: str,
        item_id: str,
        claimant: str,
        now: str,
        admin: bool = False,
    ) -> QueueItem:
        current = _stamp(now)
        result = self._db.execute(
            """
            UPDATE queue_items
            SET status = 'acked', lease_until = NULL
            WHERE account_id = ?
              AND id = ?
              AND status = 'claimed'
              AND (? = 1 OR claimed_by = ?)
              AND (lease_until IS NULL OR lease_until >= ?)
            RETURNING *
            """,
            (account_id, item_id, _bit(admin), claimant, current),
        )
        return self._changed(result, account_id=account_id, item_id=item_id)

    def nack(
        self,
        *,
        account_id: str,
        item_id: str,
        claimant: str,
        now: str,
        requeue: bool = True,
        admin: bool = False,
    ) -> QueueItem:
        _parse(now)
        # Both engines read attempts from the pre-update row when this
        # assignment stays last. Requeue clears the claim; dead keeps claimed_by.
        flag = _bit(requeue)
        result = self._db.execute(
            """
            UPDATE queue_items
            SET status = CASE
                    WHEN ? = 0 OR (attempts + 1) >= ? THEN 'dead'
                    ELSE 'open'
                END,
                claimed_by = CASE
                    WHEN ? = 0 OR (attempts + 1) >= ? THEN claimed_by
                    ELSE NULL
                END,
                lease_until = NULL,
                attempts = attempts + 1
            WHERE account_id = ?
              AND id = ?
              AND status = 'claimed'
              AND (? = 1 OR claimed_by = ?)
            RETURNING *
            """,
            (
                flag,
                NACK_DEAD_AFTER,
                flag,
                NACK_DEAD_AFTER,
                account_id,
                item_id,
                _bit(admin),
                claimant,
            ),
        )
        return self._changed(result, account_id=account_id, item_id=item_id)

    def extend(
        self,
        *,
        account_id: str,
        item_id: str,
        claimant: str,
        now: str,
    ) -> QueueItem:
        result = self._db.execute(
            """
            UPDATE queue_items
            SET lease_until = ?
            WHERE account_id = ?
              AND id = ?
              AND status = 'claimed'
              AND claimed_by = ?
            RETURNING *
            """,
            (_lease_until(now), account_id, item_id, claimant),
        )
        return self._changed(result, account_id=account_id, item_id=item_id)

    def _changed(self, result: Result, *, account_id: str, item_id: str) -> QueueItem:
        if result.rows:
            return _item(result.rows[0])
        found = self._db.fetch_one(
            "SELECT id FROM queue_items WHERE account_id = ? AND id = ?",
            (account_id, item_id),
        )
        if found is None:
            raise NotFound(f"queue item {item_id} not found")
        raise Conflict(f"queue item {item_id} cannot change in its current state")
