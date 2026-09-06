# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6",
# ]
# ///
"""Rebuild skills/lists/INDEX.md from adopted / wanted / rejected YAML."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LISTS = ROOT / "skills" / "lists"
INDEX = LISTS / "INDEX.md"


def load(name: str) -> dict:
    return yaml.safe_load((LISTS / name).read_text()) or {}


def cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value).replace("|", "\\|").replace("\n", " ")


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return "\n".join([head, sep, body])


def item_rows(items: list[dict], extra: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in items:
        row = [
            f"`{item.get('id', '')}`",
            cell(item.get("name")),
            cell(item.get("kind")),
            cell(item.get("capability")),
            cell(item.get("roles") or item.get("reason")),
            cell(item.get("verdict") or item.get("reason")),
        ]
        for key in extra:
            row.append(cell(item.get(key)))
        rows.append(row)
    return rows


def main() -> None:
    adopted = load("adopted.yaml")
    wanted = load("wanted.yaml")
    rejected = load("rejected.yaml")
    sources = load("sources.yaml")

    adopted_tbl = table(
        ["id", "name", "kind", "capability", "roles", "verdict", "install"],
        item_rows(adopted.get("items") or [], ["install"]),
    )
    wanted_tbl = table(
        ["id", "name", "kind", "capability", "roles", "verdict", "next_action"],
        item_rows(wanted.get("items") or [], ["next_action"]),
    )
    rejected_tbl = table(
        ["id", "name", "kind", "capability", "roles", "reason", "source"],
        item_rows(rejected.get("items") or [], ["source"]),
    )

    pass_date = sources.get("pass", "")
    actor = sources.get("actor", "")
    registries = sources.get("registries") or []
    reg_lines = "\n".join(
        f"- **{r.get('name')}** (`{r.get('method')}`)" for r in registries
    )

    text = f"""# Skill and MCP lists

Machine-readable source: `adopted.yaml`, `wanted.yaml`, `rejected.yaml`, `by-platform.yaml`, `sources.yaml`.

Rebuild: `uv run scripts/rebuild_skill_index.py`.

**Last maintainer pass:** {pass_date} by `{actor}`.

Owner: [`skills/skill-maintainer/SKILL.md`](../skill-maintainer/SKILL.md) (seldom). Discovery still runs the catalog skill at the start of a cycle; this folder is what the maintainer writes.

Narrative inventory: [`docs/catalogs/skills-and-mcps.md`](../../docs/catalogs/skills-and-mcps.md).

## Registries this pass

{reg_lines}

## Adopted

{adopted_tbl}

## Wanted (next attach / fork / gap)

{wanted_tbl}

## Rejected

{rejected_tbl}

## Platform map

See [`by-platform.yaml`](by-platform.yaml) for `docs/catalogs/platforms.md` ids → list ids.
"""
    INDEX.write_text(text)
    print(f"wrote {INDEX.relative_to(ROOT)} ({len(adopted.get('items') or [])} adopted, {len(wanted.get('items') or [])} wanted, {len(rejected.get('items') or [])} rejected)")


if __name__ == "__main__":
    main()
