"""Postgres memory pods: worker (private), track (shared), common."""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from app.constants import TRACKS
from app.sql import column_names as sql_column_names
from app.memory_policy import (
    HEARTBEAT_LIMIT,
    POD_COMMON,
    POD_KIND_COMMON,
    POD_KIND_TRACK,
    POD_KIND_WORKER,
    RECALL_LIMIT_DEFAULT,
    RECALL_LIMIT_MAX,
    WRITE_CAPS,
    WRITE_WINDOW_S,
    MemoryDenied,
    MemoryInvalid,
    MemoryNotFound,
    MemoryRateLimited,
    can_read_pod,
    clamp_importance,
    compact_body,
    content_hash,
    default_ttl_days,
    fts_match_query,
    is_hub_admin,
    is_inspector,
    kinds_for_scope,
    own_track_pod_id,
    pod_scope,
    resolve_read_pod,
    resolve_write_pod,
    track_pod_id,
    validate_kind,
    validate_write_text,
    visible_pod_ids,
    worker_id,
    worker_pod_id,
    write_budget_hint,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    pod TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    job_id TEXT,
    company TEXT,
    tags_json TEXT,
    importance INTEGER NOT NULL DEFAULT 2,
    pinned INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_track TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    last_recalled_at TEXT,
    recall_count INTEGER NOT NULL DEFAULT 0,
    solidify_status TEXT NOT NULL DEFAULT 'none',
    recording_id TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_pod_hash
    ON memory_items(pod, content_hash);
CREATE INDEX IF NOT EXISTS idx_memory_pod ON memory_items(pod);
CREATE INDEX IF NOT EXISTS idx_memory_kind ON memory_items(kind);
CREATE INDEX IF NOT EXISTS idx_memory_expires ON memory_items(expires_at);
CREATE INDEX IF NOT EXISTS idx_memory_created_by ON memory_items(created_by, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_recording ON memory_items(recording_id);
"""

class MemoryPrincipal(Protocol):
    role: str
    actor: str
    user_id: str | None
    track: str | None
    kind: str | None


class HasConn(Protocol):
    conn: Any

    def commit(self) -> None: ...


def _new_id(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(16).replace("-", "").replace("_", "")[:26]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_future(days: int, now: datetime | None = None) -> str:
    when = (now or datetime.now(timezone.utc)) + timedelta(days=days)
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _column_names(conn: Any, table: str) -> set[str]:
    try:
        return sql_column_names(conn, table)
    except Exception:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_memory_schema(conn: Any) -> None:
    conn.executescript(SCHEMA)
    cols = _column_names(conn, "memory_items")
    if "solidify_status" not in cols:
        conn.execute(
            "ALTER TABLE memory_items ADD COLUMN solidify_status TEXT NOT NULL DEFAULT 'none'"
        )
    if "recording_id" not in cols:
        conn.execute("ALTER TABLE memory_items ADD COLUMN recording_id TEXT")


def _load_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def row_to_item(row: Any, *, compact: bool = False) -> dict[str, Any]:
    data = dict(row)
    body = data["body"]
    item = {
        "id": data["id"],
        "pod": data["pod"],
        "pod_scope": pod_scope(data["pod"]),
        "kind": data["kind"],
        "title": data["title"],
        "body": compact_body(body) if compact else body,
        "job_id": data["job_id"] or None,
        "company": data["company"] or None,
        "tags": _load_tags(data.get("tags_json")),
        "importance": int(data["importance"] or 2),
        "pinned": bool(data["pinned"]),
        "created_by": data["created_by"],
        "created_track": data["created_track"] or None,
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "expires_at": data["expires_at"] or None,
        "recall_count": int(data["recall_count"] or 0),
        "solidify_status": data.get("solidify_status") or "none",
        "recording_id": data.get("recording_id") or None,
    }
    return item


def live_clause(now_iso: str) -> str:
    return "(expires_at IS NULL OR expires_at = '' OR expires_at > ?)"


def purge_expired(db: HasConn, *, now_iso: str | None = None) -> int:
    now = now_iso or utc_now()
    cur = db.conn.execute(
        "DELETE FROM memory_items WHERE expires_at IS NOT NULL AND expires_at != '' AND expires_at <= ?",
        (now,),
    )
    deleted = int(cur.rowcount or 0)
    if deleted:
        db.conn.commit()
    return deleted


SCOPE_DEFAULT_KIND = {
    POD_KIND_WORKER: "fact",
    POD_KIND_TRACK: "process_note",
    POD_KIND_COMMON: "process_note",
}


def pod_catalog(principal: MemoryPrincipal) -> list[dict[str, Any]]:
    own_worker = worker_pod_id(principal)
    own_track = own_track_pod_id(principal)
    admin = is_hub_admin(principal)
    pods = [
        {
            "id": own_worker,
            "scope": POD_KIND_WORKER,
            "label": "your worker (private)",
            "shared": False,
            "writable": True,
        }
    ]
    if own_track:
        track = own_track.split(":", 1)[1]
        pods.append(
            {
                "id": own_track,
                "scope": POD_KIND_TRACK,
                "label": f"{track} track (shared)",
                "shared": True,
                "writable": True,
            }
        )
    pods.append(
        {
            "id": POD_COMMON,
            "scope": POD_KIND_COMMON,
            "label": "common (all tracks)",
            "shared": True,
            "writable": True,
        }
    )
    if is_inspector(principal):
        for track in TRACKS:
            pod = track_pod_id(track)
            if pod == own_track:
                continue
            pods.append(
                {
                    "id": pod,
                    "scope": POD_KIND_TRACK,
                    "label": f"{track} track (inspect)",
                    "shared": True,
                    "inspect": True,
                    "writable": admin,
                }
            )
    return pods


def _visible_sql(principal: MemoryPrincipal) -> tuple[str, list[Any]]:
    pods = visible_pod_ids(principal)
    placeholders = ",".join("?" for _ in pods)
    return f"pod IN ({placeholders})", list(pods)


def count_recent_writes(db: HasConn, *, writer: str, scope: str, now: datetime) -> int:
    since = (now - timedelta(seconds=WRITE_WINDOW_S)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if scope == POD_KIND_COMMON:
        pod_match = "pod = ?"
        args: list[Any] = [writer, since, POD_COMMON]
    elif scope == POD_KIND_TRACK:
        pod_match = "pod LIKE 'track:%'"
        args = [writer, since]
    else:
        pod_match = "pod LIKE 'worker:%'"
        args = [writer, since]
    cur = db.conn.execute(
        f"""
        SELECT COUNT(*) AS n FROM memory_items
        WHERE created_by = ? AND created_at >= ? AND {pod_match}
        """,
        args,
    )
    row = cur.fetchone()
    return int(row["n"] if row else 0)


def _enforce_rate(db: HasConn, principal: MemoryPrincipal, scope: str) -> None:
    cap = WRITE_CAPS[scope]
    now = datetime.now(timezone.utc)
    used = count_recent_writes(db, writer=worker_id(principal), scope=scope, now=now)
    if used >= cap:
        raise MemoryRateLimited(
            f"{scope} pod write budget exhausted ({used}/{cap} in {WRITE_WINDOW_S // 60}m). "
            "Recall existing facts instead of storing more."
        )


def get_item(db: HasConn, item_id: str) -> dict[str, Any] | None:
    cur = db.conn.execute("SELECT * FROM memory_items WHERE id = ?", (item_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def public_item(db: HasConn, item_id: str, *, compact: bool = False) -> dict[str, Any]:
    cur = db.conn.execute("SELECT * FROM memory_items WHERE id = ?", (item_id,))
    row = cur.fetchone()
    if row is None:
        raise MemoryNotFound("memory item not found")
    return row_to_item(row, compact=compact)


def list_items(
    db: HasConn,
    principal: MemoryPrincipal,
    *,
    pod: str | None = None,
    kind: str | None = None,
    q: str | None = None,
    job_id: str | None = None,
    company: str | None = None,
    limit: int = RECALL_LIMIT_DEFAULT,
    compact: bool = False,
    include_expired: bool = False,
) -> list[dict[str, Any]]:
    purge_expired(db)
    cap = max(1, min(int(limit), RECALL_LIMIT_MAX))
    now = utc_now()
    clauses: list[str] = []
    args: list[Any] = []
    if pod:
        target = resolve_read_pod(principal, pod)
        clauses.append("pod = ?")
        args.append(target)
    else:
        where, vis_args = _visible_sql(principal)
        clauses.append(where)
        args.extend(vis_args)
    if not include_expired:
        clauses.append(live_clause(now))
        args.append(now)
    if kind:
        clauses.append("kind = ?")
        args.append(kind.strip().lower())
    if job_id:
        clauses.append("job_id = ?")
        args.append(job_id.strip())
    if company:
        clauses.append("lower(COALESCE(company, '')) = lower(?)")
        args.append(company.strip())

    match = fts_match_query(q)
    if match:
        like = f"%{q.strip()}%"
        clauses.append("(title LIKE ? OR body LIKE ? OR COALESCE(company, '') LIKE ?)")
        args.extend([like, like, like])

    sql = f"""
        SELECT * FROM memory_items
        WHERE {' AND '.join(clauses)}
        ORDER BY pinned DESC, importance DESC, updated_at DESC
        LIMIT ?
    """
    cur = db.conn.execute(sql, [*args, cap])
    return [row_to_item(row, compact=compact) for row in cur.fetchall()]


def insert_item(
    db: HasConn,
    principal: MemoryPrincipal,
    *,
    pod: str | None,
    kind: str,
    title: str,
    body: str,
    job_id: str | None = None,
    company: str | None = None,
    tags: list[str] | None = None,
    importance: int | None = None,
    pinned: bool = False,
    ttl_days: int | None = None,
) -> dict[str, Any]:
    purge_expired(db)
    target = resolve_write_pod(principal, pod)
    scope = pod_scope(target)
    stored_kind = validate_kind(scope, kind)
    title_text, body_text = validate_write_text(
        kind=stored_kind, scope=scope, title=title, body=body
    )
    level = clamp_importance(importance)
    if pinned and not (is_hub_admin(principal) or getattr(principal, "kind", None) == "owner"):
        raise MemoryDenied("only a track owner or admin can pin memory")
    digest = content_hash(
        kind=stored_kind,
        title=title_text,
        body=body_text,
        company=company,
        job_id=job_id,
    )
    cur = db.conn.execute(
        "SELECT * FROM memory_items WHERE pod = ? AND content_hash = ?",
        (target, digest),
    )
    existing = cur.fetchone()
    if existing:
        item = row_to_item(existing)
        item["deduped"] = True
        return item
    _enforce_rate(db, principal, scope)
    ttl = ttl_days
    if ttl is None:
        ttl = default_ttl_days(scope=scope, kind=stored_kind, importance=level)
    if ttl is not None:
        if ttl < 1 or ttl > 365:
            raise MemoryInvalid("ttl_days must be 1–365 when set")
    now = utc_now()
    item_id = _new_id("mem_")
    writer = worker_id(principal)
    clean_tags = [str(tag).strip() for tag in (tags or []) if str(tag).strip()][:8]
    db.conn.execute(
        """
        INSERT INTO memory_items (
            id, pod, kind, title, body, job_id, company, tags_json, importance, pinned,
            content_hash, created_by, created_track, created_at, updated_at, expires_at,
            last_recalled_at, recall_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0)
        """,
        (
            item_id,
            target,
            stored_kind,
            title_text,
            body_text,
            (job_id or "").strip() or None,
            (company or "").strip() or None,
            json.dumps(clean_tags, ensure_ascii=False) if clean_tags else None,
            level,
            1 if pinned else 0,
            digest,
            writer,
            getattr(principal, "track", None),
            now,
            now,
            _iso_future(ttl) if ttl else None,
        ),
    )
    db.conn.commit()
    return public_item(db, item_id)


def touch_recalled(db: HasConn, item_ids: list[str]) -> None:
    if not item_ids:
        return
    now = utc_now()
    for item_id in item_ids:
        db.conn.execute(
            """
            UPDATE memory_items
            SET last_recalled_at = ?, recall_count = recall_count + 1
            WHERE id = ?
            """,
            (now, item_id),
        )
    db.conn.commit()


def update_item(
    db: HasConn,
    principal: MemoryPrincipal,
    item_id: str,
    *,
    title: str | None = None,
    body: str | None = None,
    pinned: bool | None = None,
    expires_at: str | None = None,
    forget: bool = False,
) -> dict[str, Any]:
    stored = get_item(db, item_id)
    if stored is None:
        raise MemoryNotFound("memory item not found")
    if not can_read_pod(principal, stored["pod"]):
        raise MemoryDenied("cannot access this memory item")
    writer = worker_id(principal)
    owns = stored["created_by"] == writer
    if forget:
        if not owns and not is_inspector(principal):
            raise MemoryDenied("cannot forget another worker's memory")
        now = utc_now()
        db.conn.execute(
            "UPDATE memory_items SET expires_at = ?, updated_at = ? WHERE id = ?",
            (now, now, item_id),
        )
        db.conn.commit()
        return public_item(db, item_id)
    if pinned is not None:
        if not (is_hub_admin(principal) or getattr(principal, "kind", None) == "owner"):
            raise MemoryDenied("only a track owner or admin can pin memory")
    if (title is not None or body is not None) and not owns and not is_hub_admin(principal):
        raise MemoryDenied("cannot edit another worker's memory")
    new_title = title if title is not None else stored["title"]
    new_body = body if body is not None else stored["body"]
    if title is not None or body is not None:
        new_title, new_body = validate_write_text(
            kind=stored["kind"],
            scope=pod_scope(stored["pod"]),
            title=new_title,
            body=new_body,
        )
    now = utc_now()
    pin_val = stored["pinned"] if pinned is None else (1 if pinned else 0)
    exp = stored["expires_at"] if expires_at is None else expires_at
    digest = content_hash(
        kind=stored["kind"],
        title=new_title,
        body=new_body,
        company=stored.get("company"),
        job_id=stored.get("job_id"),
    )
    db.conn.execute(
        """
        UPDATE memory_items
        SET title = ?, body = ?, pinned = ?, expires_at = ?, content_hash = ?, updated_at = ?
        WHERE id = ?
        """,
        (new_title, new_body, pin_val, exp, digest, now, item_id),
    )
    db.conn.commit()
    return public_item(db, item_id)


def delete_item(db: HasConn, principal: MemoryPrincipal, item_id: str) -> dict[str, Any]:
    stored = get_item(db, item_id)
    if stored is None:
        raise MemoryNotFound("memory item not found")
    if not can_read_pod(principal, stored["pod"]):
        raise MemoryDenied("cannot access this memory item")
    writer = worker_id(principal)
    if stored["created_by"] != writer and not is_inspector(principal):
        raise MemoryDenied("cannot delete another worker's memory")
    db.conn.execute("DELETE FROM memory_items WHERE id = ?", (item_id,))
    db.conn.commit()
    return {"ok": True, "id": item_id, "deleted": True}


def _kind_for_move(stored_kind: str, target_scope: str, override: str | None) -> str:
    if override:
        return validate_kind(target_scope, override)
    allowed = kinds_for_scope(target_scope)
    if stored_kind in allowed:
        return stored_kind
    return validate_kind(target_scope, SCOPE_DEFAULT_KIND[target_scope])


def _can_pin(principal: MemoryPrincipal) -> bool:
    return is_hub_admin(principal) or getattr(principal, "kind", None) == "owner"


def move_item(
    db: HasConn,
    principal: MemoryPrincipal,
    item_id: str,
    *,
    pod: str,
    copy: bool = False,
    kind: str | None = None,
) -> dict[str, Any]:
    stored = get_item(db, item_id)
    if stored is None:
        raise MemoryNotFound("memory item not found")
    if not can_read_pod(principal, stored["pod"]):
        raise MemoryDenied("cannot access this memory item")
    writer = worker_id(principal)
    if stored["created_by"] != writer and not is_inspector(principal):
        raise MemoryDenied("cannot move another worker's memory")
    target = resolve_write_pod(principal, pod)
    target_scope = pod_scope(target)
    stored_kind = _kind_for_move(stored["kind"], target_scope, kind)
    title_text, body_text = stored["title"], stored["body"]
    if stored_kind != stored["kind"]:
        title_text, body_text = validate_write_text(
            kind=stored_kind,
            scope=target_scope,
            title=stored["title"],
            body=stored["body"],
        )
    digest = content_hash(
        kind=stored_kind,
        title=title_text,
        body=body_text,
        company=stored.get("company"),
        job_id=stored.get("job_id"),
    )
    if target == stored["pod"] and stored_kind == stored["kind"] and not copy:
        item = public_item(db, item_id)
        item["moved"] = False
        return item
    if copy:
        cloned = insert_item(
            db,
            principal,
            pod=target,
            kind=stored_kind,
            title=title_text,
            body=body_text,
            job_id=stored.get("job_id"),
            company=stored.get("company"),
            tags=_load_tags(stored.get("tags_json")),
            importance=int(stored.get("importance") or 2),
            pinned=bool(stored.get("pinned")) and _can_pin(principal),
        )
        cloned["copied_from"] = item_id
        return cloned
    existing = db.conn.execute(
        "SELECT * FROM memory_items WHERE pod = ? AND content_hash = ?",
        (target, digest),
    ).fetchone()
    if existing and existing["id"] != item_id:
        db.conn.execute("DELETE FROM memory_items WHERE id = ?", (item_id,))
        db.conn.commit()
        item = row_to_item(existing)
        item["deduped"] = True
        item["moved"] = True
        return item
    now = utc_now()
    db.conn.execute(
        """
        UPDATE memory_items
        SET pod = ?, kind = ?, title = ?, body = ?, content_hash = ?, updated_at = ?
        WHERE id = ?
        """,
        (target, stored_kind, title_text, body_text, digest, now, item_id),
    )
    db.conn.commit()
    item = public_item(db, item_id)
    item["moved"] = True
    return item


def grouped_recall(
    db: HasConn,
    principal: MemoryPrincipal,
    *,
    q: str | None = None,
    job_id: str | None = None,
    company: str | None = None,
    limit: int = RECALL_LIMIT_DEFAULT,
    compact: bool = False,
) -> dict[str, Any]:
    items = list_items(
        db,
        principal,
        q=q,
        job_id=job_id,
        company=company,
        limit=limit,
        compact=compact,
    )
    touch_recalled(db, [item["id"] for item in items])
    buckets = {
        POD_KIND_WORKER: [],
        POD_KIND_TRACK: [],
        POD_KIND_COMMON: [],
    }
    for item in items:
        buckets.setdefault(item["pod_scope"], []).append(item)
    counts = {key: len(value) for key, value in buckets.items()}
    return {
        "recall_url": "/api/memory/recall",
        "write_url": "/api/memory/items",
        "move_url": "/api/memory/items/{id}/move",
        "solidify_url": "/api/memory/items/{id}/solidify",
        "hint": "Use these facts this round. Store only if another bot would need them tomorrow. Solidify track/common facts that should become skills.",
        "pods": pod_catalog(principal),
        "items": items,
        "by_pod": buckets,
        "counts": counts,
        "query": q or None,
        "job_id": job_id or None,
        "company": company or None,
        "write_policy": write_budget_hint(),
        "kinds": {
            POD_KIND_WORKER: sorted(kinds_for_scope(POD_KIND_WORKER)),
            POD_KIND_TRACK: sorted(kinds_for_scope(POD_KIND_TRACK)),
            POD_KIND_COMMON: sorted(kinds_for_scope(POD_KIND_COMMON)),
        },
    }


def compact_recall(
    db: HasConn,
    principal: MemoryPrincipal,
    *,
    job_id: str | None = None,
    company: str | None = None,
    q: str | None = None,
    limit: int = HEARTBEAT_LIMIT,
) -> dict[str, Any]:
    payload = grouped_recall(
        db,
        principal,
        q=q,
        job_id=job_id,
        company=company,
        limit=limit,
        compact=True,
    )
    payload["compact"] = True
    return payload


def safe_compact_recall(
    db: HasConn,
    principal: MemoryPrincipal,
    *,
    job_id: str | None = None,
    company: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    try:
        return compact_recall(db, principal, job_id=job_id, company=company, q=q)
    except Exception:
        return {
            "recall_url": "/api/memory/recall",
            "write_url": "/api/memory/items",
            "move_url": "/api/memory/items/{id}/move",
            "solidify_url": "/api/memory/items/{id}/solidify",
            "hint": "memory unavailable this beat; continue the loop",
            "pods": [],
            "items": [],
            "by_pod": {},
            "counts": {},
            "write_policy": write_budget_hint(),
            "compact": True,
        }


OPEN_SOLIDIFY_STATUSES = frozenset({"queued", "proctoring", "passed", "promoted"})
CLOSED_SOLIDIFY_RETRY = frozenset({"failed", "declined"})

TRACK_SKILL_LANE = {
    "discovery": {
        "role": "discovery",
        "tag": "source",
        "inputs": ["job"],
        "outputs": ["apply_packet"],
    },
    "application": {
        "role": "apply",
        "tag": "apply",
        "inputs": ["job", "apply_packet"],
        "outputs": ["proof"],
    },
    "outreach": {
        "role": "outreach",
        "tag": "outreach",
        "inputs": ["job", "outreach_packet"],
        "outputs": ["touch"],
    },
    "maintenance": {
        "role": "maintain",
        "tag": "maintain",
        "inputs": ["registry"],
        "outputs": ["skills_lists"],
    },
}

ATS_HINTS = (
    ("greenhouse", ("greenhouse",)),
    ("workday", ("workday", "myworkdayjobs")),
    ("lever", ("lever.co", " lever")),
    ("ashby", ("ashby",)),
    ("linkedin", ("linkedin", "easy apply")),
)

ATS_MATCH = {
    "greenhouse": {
        "url_patterns": ["boards.greenhouse.io/*", "*.greenhouse.io/*"],
        "apply_kind": ["ats"],
    },
    "workday": {
        "url_patterns": ["*.myworkdayjobs.com/*", "*workday.com/*"],
        "apply_kind": ["ats"],
    },
    "lever": {
        "url_patterns": ["jobs.lever.co/*"],
        "apply_kind": ["ats"],
    },
    "ashby": {
        "url_patterns": ["jobs.ashbyhq.com/*"],
        "apply_kind": ["ats"],
    },
    "linkedin": {
        "url_patterns": ["*.linkedin.com/*"],
        "apply_kind": ["easy_apply"],
    },
}

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def set_solidify_status(
    db: HasConn,
    item_id: str,
    *,
    status: str,
    recording_id: str | None = None,
) -> None:
    stored = get_item(db, item_id)
    if stored is None:
        return
    now = utc_now()
    rec_id = recording_id if recording_id is not None else stored.get("recording_id")
    db.conn.execute(
        """
        UPDATE memory_items
        SET solidify_status = ?, recording_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, rec_id, now, item_id),
    )
    db.conn.commit()


def _slug_from_title(title: str, item_id: str) -> str:
    base = _SLUG_STRIP.sub("-", (title or "").lower()).strip("-")[:50]
    if not base:
        tail = re.sub(r"[^a-z0-9]", "", item_id.lower())[-12:] or "fact"
        base = tail
    return f"mem-{base}"[:80]


def _platform_from_text(text: str) -> str:
    lowered = text.lower()
    for platform, needles in ATS_HINTS:
        if any(needle in lowered for needle in needles):
            return platform
    return ""


def skill_draft_from_memory(item: dict[str, Any]) -> dict[str, Any]:
    """Turn a track/common memory fact into a skill recording payload."""
    scope = pod_scope(item["pod"])
    if scope == POD_KIND_WORKER:
        raise MemoryDenied("private worker notes cannot become skills")
    if scope == POD_KIND_COMMON:
        lane = TRACK_SKILL_LANE["maintenance"]
    else:
        track = item["pod"].split(":", 1)[1] if ":" in item["pod"] else ""
        lane = TRACK_SKILL_LANE.get(track) or TRACK_SKILL_LANE["maintenance"]
    kind_tag = str(item.get("kind") or "").replace("_", "-")
    tags = [lane["tag"]]
    if kind_tag and kind_tag not in tags:
        tags.append(kind_tag)
    for extra in item.get("tags") or []:
        cleaned = _SLUG_STRIP.sub("-", str(extra).lower()).strip("-")
        if cleaned and cleaned not in tags:
            tags.append(cleaned)
    blob = f"{item.get('title') or ''} {item.get('body') or ''}"
    platform = _platform_from_text(blob)
    if platform and platform not in tags:
        tags.append(platform)
    hints = ATS_MATCH.get(platform) or {}
    match = {
        "ats": [platform] if platform else [],
        "url_patterns": list(hints.get("url_patterns") or []),
        "apply_kind": list(hints.get("apply_kind") or []),
    }
    company = (item.get("company") or "").strip()
    body_parts = [
        f"# {item['title']}",
        "",
        f"Solidified from Hub memory `{item['id']}` (`{item['pod']}`, `{item.get('kind')}`).",
        "",
        str(item.get("body") or "").strip(),
        "",
        "## Reproducibility",
        "",
        "Keep these steps generic to the matching board or ATS. Do not pin them to one posting.",
    ]
    if company:
        body_parts.insert(5, f"Observed at: {company}.")
        body_parts.insert(6, "")
    return {
        "slug": _slug_from_title(str(item.get("title") or ""), str(item.get("id") or "")),
        "name": str(item.get("title") or "Memory fact")[:120],
        "kind": "skill",
        "role": lane["role"],
        "tags": tags,
        "platform": platform,
        "match": match,
        "inputs": list(lane["inputs"]),
        "outputs": list(lane["outputs"]),
        "body": "\n".join(body_parts),
        "origin": "memory",
        "origin_ref": item["id"],
        "parent_skill_id": None,
        "reproducible": True,
        "memory_id": item["id"],
        "memory_pod": item["pod"],
        "memory_kind": item.get("kind"),
        "source_skill_id": None,
        "source_scope": "memory",
    }
