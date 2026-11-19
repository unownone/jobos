"""Append-only job events."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.tenant import TenantContext


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _load(raw: str | None, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    return json.loads(raw)


class EventsRepo:
    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def add_event(
        self,
        tenant: TenantContext,
        *,
        job_id: str | None,
        actor_role: str,
        actor: str | None,
        action: str,
        from_status: str | None = None,
        to_status: str | None = None,
        note: str | None = None,
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ts = _utc_now()
        cur = self.conn.execute(
            """
            INSERT INTO events (
                account_id, ts, job_id, actor_role, actor, action, from_status, to_status, note, fields_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant.account_id,
                ts,
                job_id,
                actor_role,
                actor or "",
                action,
                from_status,
                to_status,
                note or "",
                _dump(fields) if fields else None,
            ),
        )
        self.conn.commit()
        return {
            "id": cur.lastrowid,
            "ts": ts,
            "job_id": job_id,
            "actor_role": actor_role,
            "actor": actor or "",
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "note": note or "",
            "fields": fields or {},
        }

    def list_events(
        self,
        tenant: TenantContext,
        *,
        job_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 10000))
        if job_id:
            cur = self.conn.execute(
                "SELECT * FROM events WHERE account_id = ? AND job_id = ? ORDER BY id DESC LIMIT ?",
                (tenant.account_id, job_id, limit),
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM events WHERE account_id = ? ORDER BY id DESC LIMIT ?",
                (tenant.account_id, limit),
            )
        out: list[dict[str, Any]] = []
        for row in cur.fetchall():
            out.append(
                {
                    "id": row["id"],
                    "ts": row["ts"],
                    "job_id": row["job_id"],
                    "actor_role": row["actor_role"],
                    "actor": row["actor"] or "",
                    "action": row["action"],
                    "from_status": row["from_status"],
                    "to_status": row["to_status"],
                    "note": row["note"] or "",
                    "fields": _load(row["fields_json"], {}),
                }
            )
        return out

    def count_to_status_since(self, tenant: TenantContext, to_status: str, since: str) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(DISTINCT job_id) AS n FROM events
            WHERE account_id = ? AND to_status = ? AND ts >= ?
            """,
            (tenant.account_id, to_status, since),
        ).fetchone()
        return int(row["n"]) if row else 0
