"""Postgres memory pods: worker (private), track (shared), common."""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from app.constants import TRACKS
from app.tenant import account_id_of
from app.storage.repos import memory as memory_repo
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


def ensure_memory_schema(conn: Any) -> None:
    memory_repo.ensure_schema(conn)


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
    """Live-row predicate. Bind ``now_iso`` to the placeholder."""
    return memory_repo.LIVE_CLAUSE


def purge_expired(db: HasConn, *, now_iso: str | None = None) -> int:
    now = now_iso or utc_now()
    deleted = memory_repo.delete_expired(db.conn, now)
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
                    "label": f"{track} track (shared)" if admin else f"{track} track (inspect)",
                    "shared": True,
                    "inspect": True,
                    "writable": admin,
                }
            )
    return pods


def count_recent_writes(db: HasConn, *, writer: str, scope: str, now: datetime, principal: MemoryPrincipal) -> int:
    since = (now - timedelta(seconds=WRITE_WINDOW_S)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return memory_repo.count_recent_writes(
        db.conn,
        account_id=account_id_of(principal),
        writer=writer,
        since=since,
        scope=scope,
    )


def _enforce_rate(db: HasConn, principal: MemoryPrincipal, scope: str) -> None:
    cap = WRITE_CAPS[scope]
    now = datetime.now(timezone.utc)
    used = count_recent_writes(db, writer=worker_id(principal), scope=scope, now=now, principal=principal)
    if used >= cap:
        raise MemoryRateLimited(
            f"{scope} pod write budget exhausted ({used}/{cap} in {WRITE_WINDOW_S // 60}m). "
            "Recall existing facts instead of storing more."
        )


def get_item(db: HasConn, item_id: str, *, principal: MemoryPrincipal | None = None) -> dict[str, Any] | None:
    row = memory_repo.fetch_item(db.conn, item_id, account_id_of(principal))
    return dict(row) if row else None


def public_item(db: HasConn, item_id: str, *, compact: bool = False, principal: MemoryPrincipal | None = None) -> dict[str, Any]:
    row = memory_repo.fetch_item(db.conn, item_id, account_id_of(principal))
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
    target = resolve_read_pod(principal, pod) if pod else None
    rows = memory_repo.list_items(
        db.conn,
        account_id=account_id_of(principal),
        pod=target,
        visible_pods=None if target is not None else visible_pod_ids(principal),
        include_expired=include_expired,
        now=utc_now(),
        kind=kind.strip().lower() if kind else None,
        job_id=job_id.strip() if job_id else None,
        company=company.strip() if company else None,
        query=q,
        limit=cap,
    )
    return [row_to_item(row, compact=compact) for row in rows]


def _deduped_row(row: Any) -> dict[str, Any]:
    item = row_to_item(row)
    item["deduped"] = True
    return item


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
    aid = account_id_of(principal)
    ttl = ttl_days
    if ttl is None:
        ttl = default_ttl_days(scope=scope, kind=stored_kind, importance=level)
    ttl_invalid = ttl is not None and (ttl < 1 or ttl > 365)
    if ttl_invalid:
        existing = memory_repo.fetch_by_hash(db.conn, aid, target, digest)
        if existing is not None:
            return _deduped_row(existing)
        _enforce_rate(db, principal, scope)
        raise MemoryInvalid("ttl_days must be 1–365 when set")
    now_dt = datetime.now(timezone.utc)
    since = (now_dt - timedelta(seconds=WRITE_WINDOW_S)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now = utc_now()
    item_id = _new_id("mem_")
    writer = worker_id(principal)
    clean_tags = [str(tag).strip() for tag in (tags or []) if str(tag).strip()][:8]
    inserted = memory_repo.insert_item(
        db.conn,
        item_id=item_id,
        account_id=aid,
        pod=target,
        kind=stored_kind,
        title=title_text,
        body=body_text,
        job_id=(job_id or "").strip() or None,
        company=(company or "").strip() or None,
        tags_json=json.dumps(clean_tags, ensure_ascii=False) if clean_tags else None,
        importance=level,
        pinned=1 if pinned else 0,
        content_hash=digest,
        writer=writer,
        created_track=getattr(principal, "track", None),
        created_at=now,
        updated_at=now,
        expires_at=_iso_future(ttl) if ttl else None,
        since=since,
        scope=scope,
        cap=WRITE_CAPS[scope],
    )
    if inserted is None:
        existing = memory_repo.fetch_by_hash(db.conn, aid, target, digest)
        if existing is not None:
            return _deduped_row(existing)
        _enforce_rate(db, principal, scope)
        raise MemoryInvalid("memory item was not stored")
    db.conn.commit()
    return public_item(db, item_id, principal=principal)


def touch_recalled(db: HasConn, item_ids: list[str], *, principal: MemoryPrincipal | None = None) -> None:
    if not item_ids:
        return
    memory_repo.touch_recalled(
        db.conn,
        item_ids,
        now=utc_now(),
        account_id=account_id_of(principal),
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
    stored = get_item(db, item_id, principal=principal)
    if stored is None:
        raise MemoryNotFound("memory item not found")
    if not can_read_pod(principal, stored["pod"]):
        raise MemoryDenied("cannot access this memory item")
    writer = worker_id(principal)
    owns = stored["created_by"] == writer
    aid = account_id_of(principal)
    if forget:
        if not owns and not is_inspector(principal):
            raise MemoryDenied("cannot forget another worker's memory")
        now = utc_now()
        memory_repo.forget_item(db.conn, item_id=item_id, account_id=aid, now=now)
        db.conn.commit()
        return public_item(db, item_id, principal=principal)
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
    memory_repo.update_item(
        db.conn,
        title=new_title,
        body=new_body,
        pinned=pin_val,
        expires_at=exp,
        content_hash=digest,
        updated_at=now,
        item_id=item_id,
        account_id=aid,
    )
    db.conn.commit()
    return public_item(db, item_id, principal=principal)


def delete_item(db: HasConn, principal: MemoryPrincipal, item_id: str) -> dict[str, Any]:
    stored = get_item(db, item_id, principal=principal)
    if stored is None:
        raise MemoryNotFound("memory item not found")
    if not can_read_pod(principal, stored["pod"]):
        raise MemoryDenied("cannot access this memory item")
    writer = worker_id(principal)
    if stored["created_by"] != writer and not is_inspector(principal):
        raise MemoryDenied("cannot delete another worker's memory")
    memory_repo.delete_item(db.conn, item_id, account_id_of(principal))
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
    stored = get_item(db, item_id, principal=principal)
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
    aid = account_id_of(principal)
    if target == stored["pod"] and stored_kind == stored["kind"] and not copy:
        item = public_item(db, item_id, principal=principal)
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
    existing = memory_repo.fetch_by_hash(db.conn, aid, target, digest)
    if existing and existing["id"] != item_id:
        memory_repo.delete_item(db.conn, item_id, aid)
        db.conn.commit()
        item = row_to_item(existing)
        item["deduped"] = True
        item["moved"] = True
        return item
    memory_repo.move_item(
        db.conn,
        pod=target,
        kind=stored_kind,
        title=title_text,
        body=body_text,
        content_hash=digest,
        updated_at=utc_now(),
        item_id=item_id,
        account_id=aid,
    )
    db.conn.commit()
    item = public_item(db, item_id, principal=principal)
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
    touch_recalled(db, [item["id"] for item in items], principal=principal)
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
    principal: MemoryPrincipal | None = None,
) -> None:
    stored = get_item(db, item_id, principal=principal)
    if stored is None:
        return
    now = utc_now()
    rec_id = recording_id if recording_id is not None else stored.get("recording_id")
    memory_repo.set_solidify(
        db.conn,
        status=status,
        recording_id=rec_id,
        updated_at=now,
        item_id=item_id,
        account_id=account_id_of(principal),
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
