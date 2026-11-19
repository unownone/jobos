"""Job rows and the job list filter. SQL stays on `?` placeholders."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Sequence

from app.constants import JSON_FIELDS, LANE_FILTERS, STATUSES
from app.tenant import TenantContext

SEARCH_CAP = 48

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_Q_COLUMNS = (
    "id",
    "company",
    "title",
    "apply_url",
    "notes",
    "location",
    "description",
    "expectations",
    "pay",
    "rejection_json",
)

COLUMN_TO_FIELD = {
    "sources_json": "sources",
    "owners_json": "owners",
    "apply_packet_json": "apply_packet",
    "outreach_packet_json": "outreach_packet",
    "research_json": "research",
    "proof_json": "proof",
    "conflicts_json": "conflicts",
    "rejection_json": "rejection",
}

FIELD_TO_COLUMN = {value: key for key, value in COLUMN_TO_FIELD.items()}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

_UPDATABLE = {
    "company",
    "title",
    "location",
    "url",
    "apply_url",
    "apply_kind",
    "ats",
    "req_id",
    "status",
    "score",
    "notes",
    "description",
    "expectations",
    "pay",
    "posted_at",
    "stop_reason",
}


def _dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _load(raw: str | None, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    return json.loads(raw)


def _normalize_rejection(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        value = {}
    by = str(value.get("by") or "").strip().lower()
    if by not in {"company", "user"}:
        by = ""
    return {
        "by": by,
        "company_remarks": str(value.get("company_remarks") or ""),
        "user_remarks": str(value.get("user_remarks") or ""),
    }


def _rejection_from_row(raw: str | None) -> dict[str, str]:
    return _normalize_rejection(_load(raw, {}))


def row_to_job(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": data["id"],
        "company": data["company"],
        "title": data["title"],
        "location": data["location"] or "",
        "remote": data["remote"],
        "url": data["url"] or "",
        "apply_url": data["apply_url"] or "",
        "apply_kind": data["apply_kind"] or "",
        "ats": data["ats"] or "",
        "req_id": data["req_id"] or "",
        "sources": _load(data["sources_json"], []),
        "status": data["status"],
        "score": data["score"],
        "owners": _load(data["owners_json"], {"discovery": "", "apply": "", "outreach": ""}),
        "apply_packet": _load(data["apply_packet_json"], {}),
        "outreach_packet": _load(data["outreach_packet_json"], {}),
        "research": _load(data["research_json"], {}),
        "proof": _load(data["proof_json"], {}),
        "notes": data["notes"] or "",
        "description": data.get("description") or "",
        "expectations": data.get("expectations") or "",
        "pay": data.get("pay") or "",
        "posted_at": data.get("posted_at") or "",
        "rejection": _rejection_from_row(data.get("rejection_json")),
        "conflicts": _load(data["conflicts_json"], []),
        "stopped": bool(data["stopped"]),
        "stop_reason": data["stop_reason"] or "",
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "created_by_role": data["created_by_role"] or "",
    }


def _owners(raw: Any) -> dict[str, str]:
    base = {"discovery": "", "apply": "", "outreach": ""}
    if isinstance(raw, dict):
        for key in base:
            if key in raw and raw[key] is not None:
                base[key] = str(raw[key])
    return base


def _remote_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def cap_search_term(term: str) -> str:
    """Keep 48 characters, then escape LIKE metacharacters so they stay literal."""
    text = str(term)[:SEARCH_CAP]
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def escaped_contains(column: str) -> str:
    """Contains predicate. LIKE is rewritten to ILIKE by the Postgres adapter.

    The bound value is the capped, escaped needle. `%` and `_` in that needle
    are literals because of ESCAPE, and the surrounding wildcards are SQL.
    """
    if not isinstance(column, str) or _IDENT.fullmatch(column) is None:
        raise ValueError(f"unsafe column name: {column!r}")
    return f"{column} LIKE ('%' || ? || '%') ESCAPE '\\'"


def _jobs_where(
    tenant: TenantContext,
    *,
    status: str | None = None,
    q: str | None = None,
    stopped: bool | None = None,
    score_min: float | None = None,
    score_max: float | None = None,
    location: str | None = None,
    apply_kind: str | None = None,
    source: str | None = None,
    remote: str | None = None,
    has_pay: bool | None = None,
    company: str | None = None,
    lane: str | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = ["account_id = ?"]
    args: list[Any] = [tenant.account_id]
    if status:
        clauses.append("status = ?")
        args.append(status)
    if lane:
        lane_statuses = LANE_FILTERS.get(lane.strip().lower())
        if lane_statuses:
            placeholders = ", ".join("?" for _ in lane_statuses)
            clauses.append(f"status IN ({placeholders})")
            args.extend(sorted(lane_statuses))
    if stopped is not None:
        clauses.append("stopped = ?")
        args.append(1 if stopped else 0)
    if q:
        needle = cap_search_term(q)
        clauses.append("(" + " OR ".join(escaped_contains(column) for column in _Q_COLUMNS) + ")")
        args.extend([needle] * len(_Q_COLUMNS))
    if company:
        clauses.append(escaped_contains("company"))
        args.append(cap_search_term(company))
    if location:
        clauses.append(escaped_contains("location"))
        args.append(cap_search_term(location))
    if apply_kind:
        clauses.append("apply_kind = ?")
        args.append(apply_kind)
    if source:
        clauses.append(escaped_contains("sources_json"))
        args.append(cap_search_term(source))
    if score_min is not None:
        clauses.append("score IS NOT NULL AND score >= ?")
        args.append(score_min)
    if score_max is not None:
        clauses.append("score IS NOT NULL AND score <= ?")
        args.append(score_max)
    remote_key = (remote or "").strip().lower()
    if remote_key in {"remote", "true", "yes"}:
        clauses.append(
            "remote IS NOT NULL AND remote != '' AND lower(remote) NOT IN ('false','0','no','onsite')"
        )
    elif remote_key in {"onsite", "false", "no"}:
        clauses.append(
            "(remote IS NULL OR remote = '' OR lower(remote) IN ('false','0','no','onsite'))"
        )
    if has_pay is True:
        clauses.append("pay IS NOT NULL AND TRIM(pay) != ''")
    elif has_pay is False:
        clauses.append("(pay IS NULL OR TRIM(pay) = '')")
    return f"WHERE {' AND '.join(clauses)}", args


class JobsRepo:
    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def list_jobs(
        self,
        tenant: TenantContext,
        *,
        status: str | None = None,
        q: str | None = None,
        stopped: bool | None = None,
        score_min: float | None = None,
        score_max: float | None = None,
        location: str | None = None,
        apply_kind: str | None = None,
        source: str | None = None,
        remote: str | None = None,
        has_pay: bool | None = None,
        company: str | None = None,
        lane: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where, args = _jobs_where(
            tenant,
            status=status,
            q=q,
            stopped=stopped,
            score_min=score_min,
            score_max=score_max,
            location=location,
            apply_kind=apply_kind,
            source=source,
            remote=remote,
            has_pay=has_pay,
            company=company,
            lane=lane,
        )
        sql = f"SELECT * FROM jobs {where} ORDER BY updated_at DESC"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            args.extend([int(limit), max(0, int(offset))])
        cur = self.conn.execute(sql, args)
        return [row_to_job(row) for row in cur.fetchall()]

    def count_jobs(
        self,
        tenant: TenantContext,
        *,
        status: str | None = None,
        q: str | None = None,
        stopped: bool | None = None,
        score_min: float | None = None,
        score_max: float | None = None,
        location: str | None = None,
        apply_kind: str | None = None,
        source: str | None = None,
        remote: str | None = None,
        has_pay: bool | None = None,
        company: str | None = None,
        lane: str | None = None,
    ) -> int:
        where, args = _jobs_where(
            tenant,
            status=status,
            q=q,
            stopped=stopped,
            score_min=score_min,
            score_max=score_max,
            location=location,
            apply_kind=apply_kind,
            source=source,
            remote=remote,
            has_pay=has_pay,
            company=company,
            lane=lane,
        )
        cur = self.conn.execute(f"SELECT COUNT(*) AS n FROM jobs {where}", args)
        row = cur.fetchone()
        return int(row["n"]) if row else 0

    def status_counts(self, tenant: TenantContext) -> dict[str, int]:
        cur = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM jobs WHERE account_id = ? GROUP BY status",
            (tenant.account_id,),
        )
        return {str(row["status"]): int(row["n"]) for row in cur.fetchall()}

    def counts_by_status(self, tenant: TenantContext) -> dict[str, int]:
        found = self.status_counts(tenant)
        return {status: int(found.get(status, 0)) for status in STATUSES}

    def get_job(self, tenant: TenantContext, job_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute(
            "SELECT * FROM jobs WHERE account_id = ? AND id = ?",
            (tenant.account_id, job_id),
        )
        row = cur.fetchone()
        return row_to_job(row) if row else None

    def find_duplicate(
        self,
        tenant: TenantContext,
        *,
        apply_url: str,
        company: str,
        title: str,
        location: str,
        exclude_id: str | None = None,
    ) -> dict[str, Any] | None:
        if apply_url:
            cur = self.conn.execute(
                "SELECT * FROM jobs WHERE account_id = ? AND apply_url = ? AND apply_url != ''",
                (tenant.account_id, apply_url),
            )
            row = cur.fetchone()
            if row and row["id"] != exclude_id:
                return row_to_job(row)
        cur = self.conn.execute(
            """
            SELECT * FROM jobs
            WHERE account_id = ?
              AND lower(company) = lower(?) AND lower(title) = lower(?)
              AND lower(COALESCE(location, '')) = lower(?)
            """,
            (tenant.account_id, company, title, location or ""),
        )
        row = cur.fetchone()
        if row and row["id"] != exclude_id:
            return row_to_job(row)
        return None

    def insert_job(self, tenant: TenantContext, job: dict[str, Any]) -> dict[str, Any]:
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO jobs (
                account_id, id, company, title, location, remote, url, apply_url, apply_kind, ats, req_id,
                sources_json, status, score, owners_json, apply_packet_json, outreach_packet_json,
                research_json, proof_json, notes, description, expectations, pay, posted_at,
                rejection_json, conflicts_json, stopped, stop_reason,
                created_at, updated_at, created_by_role
            ) VALUES (
                :account_id, :id, :company, :title, :location, :remote, :url, :apply_url, :apply_kind, :ats, :req_id,
                :sources_json, :status, :score, :owners_json, :apply_packet_json, :outreach_packet_json,
                :research_json, :proof_json, :notes, :description, :expectations, :pay, :posted_at,
                :rejection_json, :conflicts_json, :stopped, :stop_reason,
                :created_at, :updated_at, :created_by_role
            )
            """,
            {
                "account_id": tenant.account_id,
                "id": job["id"],
                "company": job["company"],
                "title": job["title"],
                "location": job.get("location") or "",
                "remote": _remote_to_text(job.get("remote")),
                "url": job.get("url") or "",
                "apply_url": job.get("apply_url") or "",
                "apply_kind": job.get("apply_kind") or "",
                "ats": job.get("ats") or "",
                "req_id": job.get("req_id") or "",
                "sources_json": _dump(job.get("sources") or []),
                "status": job.get("status") or "discovered",
                "score": job.get("score"),
                "owners_json": _dump(_owners(job.get("owners"))),
                "apply_packet_json": _dump(job.get("apply_packet") or {}),
                "outreach_packet_json": _dump(job.get("outreach_packet") or {}),
                "research_json": _dump(job.get("research") or {}),
                "proof_json": _dump(job.get("proof") or {}),
                "notes": job.get("notes") or "",
                "description": job.get("description") or "",
                "expectations": job.get("expectations") or "",
                "pay": job.get("pay") or "",
                "posted_at": job.get("posted_at") or "",
                "rejection_json": _dump(_normalize_rejection(job.get("rejection"))),
                "conflicts_json": _dump(job.get("conflicts") or []),
                "stopped": 1 if job.get("stopped") else 0,
                "stop_reason": job.get("stop_reason") or "",
                "created_at": job.get("created_at") or now,
                "updated_at": job.get("updated_at") or now,
                "created_by_role": job.get("created_by_role") or "",
            },
        )
        self.conn.commit()
        stored = self.get_job(tenant, job["id"])
        if stored is None:
            raise RuntimeError("insert did not persist")
        return stored

    def update_job(self, tenant: TenantContext, job_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        if not fields:
            stored = self.get_job(tenant, job_id)
            if stored is None:
                raise KeyError(job_id)
            return stored
        assignments: list[str] = []
        values: dict[str, Any] = {
            "id": job_id,
            "account_id": tenant.account_id,
            "updated_at": _utc_now(),
        }
        for key, value in fields.items():
            if key in JSON_FIELDS:
                col = FIELD_TO_COLUMN[key]
                assignments.append(f"{col} = :{col}")
                values[col] = _dump(_normalize_rejection(value) if key == "rejection" else value)
            elif key == "remote":
                assignments.append("remote = :remote")
                values["remote"] = _remote_to_text(value)
            elif key == "stopped":
                assignments.append("stopped = :stopped")
                values["stopped"] = 1 if value else 0
            elif key in _UPDATABLE:
                assignments.append(f"{key} = :{key}")
                values[key] = value
        assignments.append("updated_at = :updated_at")
        self.conn.execute(
            f"UPDATE jobs SET {', '.join(assignments)} WHERE account_id = :account_id AND id = :id",
            values,
        )
        self.conn.commit()
        stored = self.get_job(tenant, job_id)
        if stored is None:
            raise KeyError(job_id)
        return stored

    def delete_job(self, tenant: TenantContext, job_id: str) -> None:
        self.conn.execute(
            "DELETE FROM jobs WHERE account_id = ? AND id = ?",
            (tenant.account_id, job_id),
        )
        self.conn.commit()

    def delete_jobs_for_account(self, account_id: str) -> int:
        """Delete every job for one account in one statement."""
        cur = self.conn.execute("DELETE FROM jobs WHERE account_id = ?", (account_id,))
        self.conn.commit()
        return int(cur.rowcount)

    def count_created_since(self, tenant: TenantContext, since: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE account_id = ? AND created_at >= ?",
            (tenant.account_id, since),
        ).fetchone()
        return int(row["n"]) if row else 0

    def oldest_open(
        self, tenant: TenantContext, statuses: Sequence[str]
    ) -> dict[str, Any] | None:
        if not statuses:
            return None
        placeholders = ", ".join("?" for _ in statuses)
        row = self.conn.execute(
            f"""
            SELECT * FROM jobs
            WHERE account_id = ?
              AND stopped = 0
              AND status IN ({placeholders})
            ORDER BY COALESCE(NULLIF(posted_at, ''), created_at) ASC
            LIMIT 1
            """,
            (tenant.account_id, *statuses),
        ).fetchone()
        return row_to_job(row) if row else None
