# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6",
# ]
# ///
"""Rebuild ledger/INDEX.md from ledger/jobs/*.yaml. Skips files starting with _."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / "ledger" / "jobs"
INDEX = ROOT / "ledger" / "INDEX.md"

OPERATORS_RE = re.compile(
    r"(## Active operators.*?)(?=\n## Jobs\n)",
    re.DOTALL,
)

DEFAULT_OPERATORS = """## Active operators

| role | name | scope | since |
| --- | --- | --- | --- |
| discovery | _unclaimed_ | all portals | |
| apply | _unclaimed_ | all ATS | |
| outreach | _unclaimed_ | email + linkedin_dm | |
| maintainer | _unclaimed_ | skills + lists | |
"""


def load_jobs() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(JOBS.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        data = yaml.safe_load(path.read_text()) or {}
        if not isinstance(data, dict) or not data.get("id"):
            raise SystemExit(f"invalid job file: {path}")
        rows.append(data)
    rows.sort(key=lambda j: (str(j.get("status") or ""), str(j.get("id") or "")))
    return rows


def next_action(job: dict) -> str:
    status = str(job.get("status") or "")
    mapping = {
        "discovered": "enrich / score",
        "enriching": "finish research",
        "shortlisted": "human gate or mark apply_ready",
        "skipped": "—",
        "apply_ready": "apply packet ready",
        "applying": "finish submit",
        "applied": "seed outreach",
        "apply_blocked": "human: " + str(job.get("notes") or "blocked"),
        "outreach_ready": "send email+dm",
        "outreaching": "finish touches",
        "waiting": "wait for reply",
        "chatting": "continue thread",
        "interview": "interview loop",
        "offer": "decision",
        "closed_rejected": "—",
        "closed_withdrawn": "—",
        "closed_expired": "—",
    }
    return mapping.get(status, status)


APPLY_STATUSES = {
    "applying",
    "applied",
    "apply_blocked",
    "outreach_ready",
}
OUTREACH_STATUSES = {
    "outreaching",
    "waiting",
    "chatting",
    "interview",
    "offer",
}


def owner(job: dict) -> str:
    owners = job.get("owners") or {}
    if not isinstance(owners, dict):
        return ""
    status = str(job.get("status") or "")
    if status in APPLY_STATUSES:
        return str(owners.get("apply") or owners.get("discovery") or "")
    if status in OUTREACH_STATUSES:
        return str(owners.get("outreach") or owners.get("apply") or "")
    return str(owners.get("discovery") or "")


def cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "/").replace("\n", " ").strip()


def render(jobs: list[dict], operators: str) -> str:
    lines = [
        "# Ledger INDEX",
        "",
        "Human board. Canonical data lives in `jobs/*.yaml`. Rebuild with `uv run scripts/rebuild_index.py`.",
        "",
        operators.rstrip(),
        "",
        "## Jobs",
        "",
        "| id | company | title | source | status | score | owner | next |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    if not jobs:
        lines.append("| _empty_ | | | | | | | clone example from `jobs/_example.yaml` when live |")
    else:
        for job in jobs:
            sources = job.get("sources") or []
            source = ",".join(sources) if isinstance(sources, list) else sources
            lines.append(
                "| {id} | {company} | {title} | {source} | {status} | {score} | {owner} | {next} |".format(
                    id=cell(job.get("id")),
                    company=cell(job.get("company")),
                    title=cell(job.get("title")),
                    source=cell(source),
                    status=cell(job.get("status")),
                    score=cell(job.get("score")),
                    owner=cell(owner(job)),
                    next=cell(next_action(job)),
                )
            )
    lines.extend(
        [
            "",
            "## How to update",
            "",
            "1. Edit or add `ledger/jobs/<id>.yaml`",
            "2. Append one line to `events.jsonl`",
            "3. Refresh the row above (or run the rebuild script)",
            "",
        ]
    )
    return "\n".join(lines)


def extract_operators(existing: str) -> str:
    match = OPERATORS_RE.search(existing)
    if match:
        return match.group(1).strip()
    return DEFAULT_OPERATORS.strip()


def main() -> None:
    operators = DEFAULT_OPERATORS.strip()
    if INDEX.exists():
        operators = extract_operators(INDEX.read_text())
    jobs = load_jobs()
    INDEX.write_text(render(jobs, operators))
    print(f"wrote {INDEX.relative_to(ROOT)} ({len(jobs)} jobs)")


if __name__ == "__main__":
    main()
