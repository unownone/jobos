# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6",
# ]
# ///
"""Import ledger/jobs YAML (+ optional events.jsonl) into the hunt board SQLite DB.

Maintainer / maintenance hygiene. Skips `_*.yaml`. Does not copy resume PDFs or secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "board"))

from app.db import BoardDB  # noqa: E402

STATUSES = {
    "discovered",
    "enriching",
    "shortlisted",
    "skipped",
    "apply_ready",
    "applying",
    "applied",
    "apply_blocked",
    "outreach_ready",
    "outreaching",
    "waiting",
    "chatting",
    "interview",
    "offer",
    "closed_rejected",
    "closed_withdrawn",
    "closed_expired",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Import git ledger history into the hunt board DB")
    parser.add_argument("--db", default=str(ROOT / "board" / "data" / "board.db"))
    parser.add_argument("--jobs-dir", default=str(ROOT / "ledger" / "jobs"))
    parser.add_argument("--events", default=str(ROOT / "ledger" / "events.jsonl"))
    args = parser.parse_args()

    board = BoardDB(Path(args.db))
    created = 0
    updated = 0
    skipped = 0
    for path in sorted(Path(args.jobs_dir).glob("*.yaml")):
        if path.name.startswith("_"):
            skipped += 1
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict) or not raw.get("id") or not raw.get("company"):
            skipped += 1
            continue
        status = raw.get("status") or "discovered"
        if status not in STATUSES:
            skipped += 1
            continue
        row = {
            "id": raw["id"],
            "company": raw["company"],
            "title": raw.get("title") or "",
            "location": raw.get("location") or "",
            "remote": raw.get("remote"),
            "url": raw.get("url") or "",
            "apply_url": raw.get("apply_url") or "",
            "apply_kind": raw.get("apply_kind") or "",
            "ats": raw.get("ats") or "",
            "req_id": str(raw.get("req_id") or ""),
            "sources": raw.get("sources") or [],
            "status": status,
            "score": raw.get("score"),
            "owners": raw.get("owners") or {},
            "apply_packet": raw.get("apply_packet") or {},
            "outreach_packet": raw.get("outreach_packet") or {},
            "research": raw.get("research") or {},
            "proof": raw.get("proof") or {},
            "notes": raw.get("notes") or "",
            "conflicts": raw.get("conflicts") or [],
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
            "created_by_role": "maintenance",
        }
        existing = board.get_job(row["id"])
        if existing:
            board.update_job(row["id"], {k: v for k, v in row.items() if k != "id"})
            updated += 1
        else:
            board.insert_job(row)
            created += 1

    events_path = Path(args.events)
    imported_events = 0
    if events_path.is_file():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            board.add_event(
                job_id=payload.get("job_id"),
                actor_role=str(payload.get("role") or "system"),
                actor=str(payload.get("actor") or ""),
                action=str(payload.get("action") or "ledger_import"),
                from_status=payload.get("from"),
                to_status=payload.get("to"),
                note=str(payload.get("note") or ""),
            )
            imported_events += 1

    board.add_event(
        job_id=None,
        actor_role="maintenance",
        actor="board_import_ledger",
        action="import",
        note=f"created={created} updated={updated} skipped={skipped} events={imported_events}",
    )
    print(f"db={args.db} created={created} updated={updated} skipped={skipped} events={imported_events}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
