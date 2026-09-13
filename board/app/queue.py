"""Work queue: claim / ack / nack / leases. Phase D. Not chat, presence, or onboarding."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.auth import Principal
from app.bootstrap import new_id
from app.db import BoardDB, utc_now
from app.memory_store import safe_compact_recall
from app.pack import catalog_updated_at
from app.settings import BOARD_DIR

LEASE_MINUTES = 15
NACK_DEAD_AFTER = 5
CATALOG_MAX_AGE_DAYS = 7
QUEUE_STATUSES = ("open", "claimed", "acked", "dead")

QUEUE_SCHEMA = """
CREATE TABLE IF NOT EXISTS queue_items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    track TEXT,
    job_id TEXT,
    payload_json TEXT,
    status TEXT NOT NULL,
    claimed_by TEXT,
    lease_until TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    dedupe_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_queue_status_kind ON queue_items(status, kind);
CREATE INDEX IF NOT EXISTS idx_queue_claimed_by ON queue_items(claimed_by);
CREATE INDEX IF NOT EXISTS idx_queue_job ON queue_items(job_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_kind_job
    ON queue_items(kind, job_id)
    WHERE job_id IS NOT NULL AND job_id != '';
"""

QUEUE_KINDS = (
    "catalog.refresh",
    "discovery.search",
    "discovery.enrich",
    "discovery.packet",
    "apply.ready",
    "apply.blocked_retry",
    "outreach.ready",
    "maintenance.hygiene",
    "maintenance.pack_rebuild",
    "skill.record",
)

JOB_SCOPED_KINDS = frozenset(
    {
        "discovery.enrich",
        "discovery.packet",
        "apply.ready",
        "apply.blocked_retry",
        "outreach.ready",
    }
)

SYSTEM_KINDS = frozenset({"apply.ready", "outreach.ready"})
MESSAGE_KIND = "message"

KIND_CONSUMER_TRACK = {
    "catalog.refresh": None,
    "discovery.search": "discovery",
    "discovery.enrich": "discovery",
    "discovery.packet": "discovery",
    "apply.ready": "application",
    "apply.blocked_retry": "application",
    "outreach.ready": "outreach",
    "maintenance.hygiene": "maintenance",
    "maintenance.pack_rebuild": "maintenance",
    "skill.record": "maintenance",
}

CONSUME_KINDS: dict[str, frozenset[str]] = {
    "discovery": frozenset(
        {"catalog.refresh", "discovery.search", "discovery.enrich", "discovery.packet"}
    ),
    "apply": frozenset({"apply.ready", "apply.blocked_retry"}),
    "outreach": frozenset({"outreach.ready"}),
    "maintenance": frozenset(
        {
            "catalog.refresh",
            "maintenance.hygiene",
            "maintenance.pack_rebuild",
            "skill.record",
        }
    ),
    "admin": frozenset(QUEUE_KINDS),
}

PRODUCE_KINDS: dict[str, frozenset[str]] = {
    "discovery": frozenset(
        {
            "catalog.refresh",
            "discovery.search",
            "discovery.enrich",
            "discovery.packet",
            "skill.record",
        }
    ),
    "apply": frozenset({"skill.record"}),
    "outreach": frozenset({"skill.record"}),
    "maintenance": frozenset(
        {
            "catalog.refresh",
            "maintenance.hygiene",
            "maintenance.pack_rebuild",
            "skill.record",
        }
    ),
    "admin": frozenset(QUEUE_KINDS),
}

NETWORK_APPLY_KINDS = frozenset({"network", "outreach_only"})


def ensure_queue_schema(conn: Any) -> None:
    conn.executescript(QUEUE_SCHEMA)


def parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_minutes(now_iso: str, minutes: int) -> str:
    dt = parse_iso(now_iso) or datetime.now(timezone.utc)
    return format_iso(dt + timedelta(minutes=minutes))


def claimant_id(principal: Principal) -> str:
    if principal.user_id:
        return principal.user_id
    actor = principal.actor or "anon"
    return f"compat:{principal.role}:{actor}"


def consume_kinds_for(principal: Principal) -> frozenset[str]:
    return CONSUME_KINDS.get(principal.role, frozenset())


def produce_kinds_for(principal: Principal) -> frozenset[str]:
    return PRODUCE_KINDS.get(principal.role, frozenset())


def packet_complete(job: dict[str, Any]) -> bool:
    packet = job.get("apply_packet") or {}
    if not isinstance(packet, dict):
        return False
    url = str(packet.get("url") or "").strip()
    steps = packet.get("steps")
    return bool(url) or bool(steps)


def catalog_date_is_fresh(iso_date: str | None, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if not iso_date:
        return False
    try:
        parsed = datetime.strptime(str(iso_date)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    age_days = (now.date() - parsed.date()).days
    return age_days <= CATALOG_MAX_AGE_DAYS


def catalog_refresh_acked_recent(db: BoardDB, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    cur = db.conn.execute(
        """
        SELECT ts FROM events
        WHERE action = 'queue_ack' AND (note = 'catalog.refresh' OR fields_json LIKE '%catalog.refresh%')
        ORDER BY id DESC LIMIT 1
        """
    )
    row = cur.fetchone()
    if row is None:
        cur = db.conn.execute(
            """
            SELECT created_at FROM queue_items
            WHERE kind = 'catalog.refresh' AND status = 'acked'
            ORDER BY created_at DESC LIMIT 1
            """
        )
        row = cur.fetchone()
        if row is None:
            return False
        stamp = row["created_at"]
    else:
        stamp = row["ts"]
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (now - parsed) <= timedelta(days=CATALOG_MAX_AGE_DAYS)


def catalog_fresh_enough(db: BoardDB, pack: Any | None = None, now: datetime | None = None) -> bool:
    """Block discovery.search when catalog is older than 7 days unless catalog.refresh was acked."""
    now = now or datetime.now(timezone.utc)
    if catalog_refresh_acked_recent(db, now):
        return True
    date = None
    if pack is not None:
        try:
            date = pack.meta_without_ensure().catalog_updated_at
        except Exception:
            date = None
        if not date:
            try:
                date = catalog_updated_at(pack.repo_root)
            except Exception:
                date = None
    if not date:
        try:
            date = catalog_updated_at(BOARD_DIR.parent)
        except Exception:
            date = None
    return catalog_date_is_fresh(date, now)


def dedupe_key_for(kind: str, job_id: str | None, payload: dict[str, Any] | None) -> str:
    payload = payload or {}
    jid = (job_id or "").strip()
    if kind in JOB_SCOPED_KINDS:
        if not jid:
            raise HTTPException(status_code=422, detail=f"{kind} requires job_id")
        return f"{kind}:{jid}"
    if kind == "discovery.search":
        portal = str(payload.get("portal") or "").strip().lower()
        query = str(payload.get("query") or "").strip().lower()
        if not portal:
            raise HTTPException(status_code=422, detail="discovery.search requires payload.portal")
        return f"{kind}:{portal}:{query}"
    if kind in {"catalog.refresh", "maintenance.hygiene", "maintenance.pack_rebuild"}:
        return kind
    if kind == "skill.record":
        recording_id = str(payload.get("recording_id") or "").strip()
        if not recording_id:
            raise HTTPException(status_code=422, detail="skill.record requires payload.recording_id")
        return f"{kind}:{recording_id}"
    raise HTTPException(status_code=422, detail=f"unknown queue kind {kind}")


def public_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "track": row.get("track"),
        "job_id": row.get("job_id") or None,
        "payload": row.get("payload") or {},
        "status": row["status"],
        "claimed_by": row.get("claimed_by"),
        "lease_until": row.get("lease_until"),
        "attempts": int(row.get("attempts") or 0),
        "dedupe_key": row["dedupe_key"],
        "created_at": row["created_at"],
    }


def _row_to_item(row: Any) -> dict[str, Any]:
    payload_raw = row["payload_json"]
    if payload_raw:
        payload = json.loads(payload_raw)
    else:
        payload = {}
    return {
        "id": row["id"],
        "kind": row["kind"],
        "track": row["track"],
        "job_id": row["job_id"] or "",
        "payload": payload,
        "status": row["status"],
        "claimed_by": row["claimed_by"],
        "lease_until": row["lease_until"],
        "attempts": int(row["attempts"] or 0),
        "dedupe_key": row["dedupe_key"],
        "created_at": row["created_at"],
    }


class QueuePushIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    job_id: str | None = None
    payload: dict[str, Any] | None = None


class QueueClaimIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kinds: list[str] | None = None
    limit: int = Field(default=1, ge=1, le=8)


class QueueNackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requeue: bool = True
    note: str | None = None


class Clock:
    def __init__(self, now_fn: Callable[[], str] | None = None) -> None:
        self._override: str | None = None
        self._now_fn = now_fn or utc_now

    def now(self) -> str:
        if self._override:
            return self._override
        return self._now_fn()

    def set(self, iso: str | None) -> None:
        self._override = iso


class QueueService:
    def __init__(self, db: BoardDB, clock: Clock | None = None, pack: Any | None = None) -> None:
        self.db = db
        self.clock = clock or Clock()
        self.pack = pack
        self._claim_lock = threading.Lock()
        ensure_queue_schema(self.db.conn)
        self.db.conn.commit()

    def get(self, item_id: str) -> dict[str, Any] | None:
        cur = self.db.conn.execute("SELECT * FROM queue_items WHERE id = ?", (item_id,))
        row = cur.fetchone()
        return _row_to_item(row) if row else None

    def get_by_dedupe(self, key: str) -> dict[str, Any] | None:
        cur = self.db.conn.execute("SELECT * FROM queue_items WHERE dedupe_key = ?", (key,))
        row = cur.fetchone()
        return _row_to_item(row) if row else None

    def list_items(
        self,
        *,
        status_filter: str | None = None,
        kind: str | None = None,
        track: str | None = None,
        claimed_by: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        args: list[Any] = []
        if status_filter:
            clauses.append("status = ?")
            args.append(status_filter)
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        if track:
            clauses.append("track = ?")
            args.append(track)
        if claimed_by:
            clauses.append("claimed_by = ?")
            args.append(claimed_by)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = max(1, min(int(limit), 500))
        cur = self.db.conn.execute(
            f"SELECT * FROM queue_items {where} ORDER BY id LIMIT ?",
            [*args, limit],
        )
        return [_row_to_item(r) for r in cur.fetchall()]

    def claims_for_jobs(self, job_ids: list[str]) -> dict[str, dict[str, Any]]:
        ids = [jid for jid in job_ids if jid]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        cur = self.db.conn.execute(
            f"""
            SELECT * FROM queue_items
            WHERE status = 'claimed' AND job_id IN ({placeholders})
            """,
            ids,
        )
        out: dict[str, dict[str, Any]] = {}
        for row in cur.fetchall():
            item = public_item(_row_to_item(row))
            job_id = item.get("job_id")
            if job_id:
                out[str(job_id)] = {
                    "queue_id": item["id"],
                    "kind": item["kind"],
                    "claimed_by": item.get("claimed_by"),
                    "lease_until": item.get("lease_until"),
                }
        return out

    def upsert(
        self,
        *,
        kind: str,
        job_id: str | None,
        payload: dict[str, Any] | None,
        actor_role: str,
        actor: str | None,
        system: bool = False,
        commit: bool = True,
    ) -> dict[str, Any]:
        if kind == MESSAGE_KIND:
            raise HTTPException(
                status_code=422,
                detail="message kinds belong to a later phase; use work queue kinds only",
            )
        if kind not in QUEUE_KINDS:
            raise HTTPException(status_code=422, detail=f"unknown queue kind {kind!r}")
        payload = dict(payload or {})
        key = dedupe_key_for(kind, job_id, payload)
        existing = self.get_by_dedupe(key)
        if existing:
            return existing
        now = self.clock.now()
        item_id = new_id("qi_")
        track = KIND_CONSUMER_TRACK.get(kind)
        self.db.conn.execute(
            """
            INSERT INTO queue_items (
                id, kind, track, job_id, payload_json, status, claimed_by,
                lease_until, attempts, dedupe_key, created_at
            ) VALUES (?, ?, ?, ?, ?, 'open', NULL, NULL, 0, ?, ?)
            """,
            (
                item_id,
                kind,
                track,
                (job_id or "").strip() or None,
                json.dumps(payload, ensure_ascii=False),
                key,
                now,
            ),
        )
        if commit:
            self.db.conn.commit()
        stored = self.get(item_id)
        if stored is None:
            stored = self.get_by_dedupe(key)
        if stored is None:
            raise RuntimeError("queue insert did not persist")
        self.db.add_event(
            job_id=job_id,
            actor_role=actor_role,
            actor=actor,
            action="queue_push",
            note=kind,
            fields={"queue_id": stored["id"], "kind": kind, "system": system, "dedupe_key": key},
        )
        return stored

    def sync_system_items(
        self,
        job: dict[str, Any],
        *,
        actor_role: str,
        actor: str | None,
    ) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []
        if job.get("stopped"):
            return created
        status_value = str(job.get("status") or "")
        job_id = job["id"]
        apply_kind = str(job.get("apply_kind") or "").strip().lower()
        if status_value == "apply_ready" and packet_complete(job):
            created.append(
                self.upsert(
                    kind="apply.ready",
                    job_id=job_id,
                    payload={"job_id": job_id},
                    actor_role=actor_role,
                    actor=actor,
                    system=True,
                )
            )
        outreach_ok = status_value == "applied" or (
            apply_kind in NETWORK_APPLY_KINDS and status_value == "outreach_ready"
        )
        if outreach_ok:
            created.append(
                self.upsert(
                    kind="outreach.ready",
                    job_id=job_id,
                    payload={"job_id": job_id},
                    actor_role=actor_role,
                    actor=actor,
                    system=True,
                )
            )
        return created

    def claim(
        self,
        principal: Principal,
        *,
        kinds: list[str] | None,
        limit: int = 1,
    ) -> list[dict[str, Any]]:
        allowed = consume_kinds_for(principal)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="this principal cannot claim queue work",
            )
        requested = list(kinds) if kinds else None
        if requested:
            unknown = [k for k in requested if k not in QUEUE_KINDS]
            if unknown:
                raise HTTPException(status_code=422, detail=f"unknown queue kind {unknown[0]!r}")
            forbidden = [k for k in requested if k not in allowed]
            if forbidden:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"track cannot claim {forbidden[0]}",
                )
            claim_kinds = [k for k in requested if k in allowed]
        else:
            claim_kinds = sorted(allowed)
        if "discovery.search" in claim_kinds and not catalog_fresh_enough(self.db, pack=self.pack):
            if requested == ["discovery.search"]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="catalog stale; discovery.search blocked until catalog.refresh is acked or Last catalog pass is within 7 days",
                )
            claim_kinds = [k for k in claim_kinds if k != "discovery.search"]
        if not claim_kinds:
            return []
        who = claimant_id(principal)
        now = self.clock.now()
        lease_until = add_minutes(now, LEASE_MINUTES)
        claimed: list[dict[str, Any]] = []
        with self._claim_lock:
            placeholders = ",".join("?" for _ in claim_kinds)
            for _ in range(max(1, min(limit, 8))):
                self.db.begin_immediate()
                try:
                    cur = self.db.conn.execute(
                        f"""
                        SELECT * FROM queue_items
                         WHERE status IN ('open', 'claimed')
                           AND kind IN ({placeholders})
                           AND (
                                status = 'open'
                                OR lease_until IS NULL
                                OR lease_until = ''
                                OR lease_until < ?
                           )
                         ORDER BY id
                         LIMIT 1
                        """,
                        [*claim_kinds, now],
                    )
                    row = cur.fetchone()
                    if row is None:
                        self.db.conn.commit()
                        break
                    item = _row_to_item(row)
                    stolen = (
                        item["status"] == "claimed"
                        and item.get("claimed_by")
                        and item["claimed_by"] != who
                    )
                    prev_owner = item.get("claimed_by")
                    self.db.conn.execute(
                        """
                        UPDATE queue_items
                        SET status = 'claimed', claimed_by = ?, lease_until = ?
                        WHERE id = ?
                        """,
                        (who, lease_until, item["id"]),
                    )
                    self.db.conn.commit()
                except Exception:
                    self.db.rollback()
                    raise
                stored = self.get(item["id"])
                if stored is None:
                    continue
                if stolen:
                    self.db.add_event(
                        job_id=stored.get("job_id") or None,
                        actor_role=principal.role,
                        actor=principal.actor,
                        action="claim_expired",
                        note="lease stolen",
                        fields={
                            "queue_id": stored["id"],
                            "kind": stored["kind"],
                            "previous_claimed_by": prev_owner,
                            "claimed_by": who,
                        },
                    )
                self.db.add_event(
                    job_id=stored.get("job_id") or None,
                    actor_role=principal.role,
                    actor=principal.actor,
                    action="queue_claim",
                    note=stored["kind"],
                    fields={"queue_id": stored["id"], "kind": stored["kind"], "claimed_by": who},
                )
                if stored["kind"] in {"apply.ready", "apply.blocked_retry"} and stored.get("job_id"):
                    job = self.db.get_job(stored["job_id"])
                    if job is not None:
                        owners = dict(job.get("owners") or {})
                        owners["apply"] = principal.actor or who
                        self.db.update_job(stored["job_id"], {"owners": owners})
                claimed.append(stored)
        return claimed

    def ack(self, principal: Principal, item_id: str) -> dict[str, Any]:
        item = self.get(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="queue item not found")
        who = claimant_id(principal)
        if item["status"] != "claimed":
            raise HTTPException(status_code=409, detail="queue item is not claimed")
        if item.get("claimed_by") != who and principal.role != "admin":
            raise HTTPException(status_code=403, detail="only the claimant can ack")
        now = self.clock.now()
        if principal.role != "admin":
            until = item.get("lease_until") or ""
            if until and until < now:
                raise HTTPException(status_code=409, detail="lease expired")
        self.db.conn.execute(
            """
            UPDATE queue_items
            SET status = 'acked', lease_until = NULL
            WHERE id = ?
            """,
            (item_id,),
        )
        self.db.conn.commit()
        stored = self.get(item_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="queue item not found")
        self.db.add_event(
            job_id=stored.get("job_id") or None,
            actor_role=principal.role,
            actor=principal.actor,
            action="queue_ack",
            note=stored["kind"],
            fields={"queue_id": stored["id"], "kind": stored["kind"]},
        )
        return stored

    def nack(
        self,
        principal: Principal,
        item_id: str,
        *,
        requeue: bool = True,
        note: str | None = None,
    ) -> dict[str, Any]:
        item = self.get(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="queue item not found")
        who = claimant_id(principal)
        if item["status"] != "claimed":
            raise HTTPException(status_code=409, detail="queue item is not claimed")
        if item.get("claimed_by") != who and principal.role != "admin":
            raise HTTPException(status_code=403, detail="only the claimant can nack")
        attempts = int(item.get("attempts") or 0) + 1
        dead = (not requeue) or attempts >= NACK_DEAD_AFTER
        if dead:
            self.db.conn.execute(
                """
                UPDATE queue_items
                SET status = 'dead', attempts = ?, lease_until = NULL
                WHERE id = ?
                """,
                (attempts, item_id),
            )
        else:
            self.db.conn.execute(
                """
                UPDATE queue_items
                SET status = 'open', attempts = ?, claimed_by = NULL, lease_until = NULL
                WHERE id = ?
                """,
                (attempts, item_id),
            )
        self.db.conn.commit()
        stored = self.get(item_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="queue item not found")
        self.db.add_event(
            job_id=stored.get("job_id") or None,
            actor_role=principal.role,
            actor=principal.actor,
            action="queue_nack" if not dead else "queue_dead",
            note=note or stored["kind"],
            fields={
                "queue_id": stored["id"],
                "kind": stored["kind"],
                "attempts": attempts,
                "requeue": requeue and not dead,
            },
        )
        return stored


def _can_inspect(principal: Principal) -> bool:
    if principal.role in {"admin", "maintenance"} or principal.kind == "admin":
        return True
    return principal.kind == "owner"


def register_queue_routes(
    app: FastAPI,
    *,
    queue: QueueService,
    principal_dep: Any,
) -> None:
    router = APIRouter(prefix="/api/queue", tags=["queue"])

    @router.post("/push")
    def queue_push(
        body: QueuePushIn,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        if body.kind in SYSTEM_KINDS and principal.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="apply.ready and outreach.ready are system-enqueued on job status",
            )
        allowed = produce_kinds_for(principal)
        if body.kind not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"this track cannot push {body.kind}",
            )
        existing = None
        try:
            key = dedupe_key_for(body.kind, body.job_id, body.payload)
            existing = queue.get_by_dedupe(key)
        except HTTPException:
            existing = None
        item = queue.upsert(
            kind=body.kind,
            job_id=body.job_id,
            payload=body.payload,
            actor_role=principal.role,
            actor=principal.actor,
        )
        return {"item": public_item(item), "deduped": existing is not None}

    @router.post("/claim")
    def queue_claim(
        body: QueueClaimIn = Body(default_factory=QueueClaimIn),
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        items = queue.claim(principal, kinds=body.kinds, limit=body.limit)
        job_id = items[0].get("job_id") if items else None
        company = None
        if job_id:
            job = queue.db.get_job(job_id)
            if job:
                company = job.get("company") or None
        memory = safe_compact_recall(
            queue.db,
            principal,
            job_id=job_id,
            company=company,
        )
        return {
            "items": [public_item(i) for i in items],
            "count": len(items),
            "memory": memory,
        }

    @router.post("/ack/{item_id}")
    def queue_ack(
        item_id: str,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        item = queue.ack(principal, item_id)
        return {"item": public_item(item)}

    @router.post("/nack/{item_id}")
    def queue_nack(
        item_id: str,
        body: QueueNackIn = Body(default_factory=QueueNackIn),
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        item = queue.nack(principal, item_id, requeue=body.requeue, note=body.note)
        return {"item": public_item(item)}

    @router.get("/mine")
    def queue_mine(principal: Principal = Depends(principal_dep)) -> dict[str, Any]:
        who = claimant_id(principal)
        items = queue.list_items(status_filter="claimed", claimed_by=who, limit=200)
        return {"items": [public_item(i) for i in items], "count": len(items)}

    @router.get("")
    def queue_inspect(
        principal: Principal = Depends(principal_dep),
        status_filter: Annotated[str | None, Query(alias="status")] = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        if not _can_inspect(principal):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="only admin, maintenance, or a track owner can inspect the queue",
            )
        track = principal.track if principal.kind == "owner" else None
        items = queue.list_items(
            status_filter=status_filter,
            kind=kind,
            track=track,
            limit=limit,
        )
        return {"items": [public_item(i) for i in items], "count": len(items)}

    app.include_router(router)
