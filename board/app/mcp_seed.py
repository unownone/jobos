"""Parse skills/lists + mcp.example.json into Hub MCP registry rows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from app.mcp_store import MCP_KINDS, McpStore, content_hash_for
from app.pack import default_repo_root, repo_root_for
from app.settings import Settings

LIST_FILES: tuple[tuple[str, str], ...] = (
    ("adopted.yaml", "adopted"),
    ("wanted.yaml", "wanted"),
    ("rejected.yaml", "rejected"),
)

SKIP_KINDS = frozenset({"skill", "gap"})

# mcp.example.json / hosted JSON keys → list ids.
EXAMPLE_ALIASES: dict[str, str] = {
    "exa": "exa-mcp",
    "parallel-search": "parallel-search-mcp",
    "firecrawl": "firecrawl-mcp",
    "tavily": "tavily-mcp",
    "indeed": "indeed-mcp",
    "hunter": "hunter-mcp",
    "apollo": "apollo-people",
    "gmail": "gmail-mcp",
    "drive": "google-drive-mcp",
    "calendar": "google-calendar-mcp",
    "playwright": "playwright-mcp",
    "workatastartup": "workatastartup-mcp",
    "ats-jobs": "ats-jobs-mcp",
    "job-scout": "job-scout-mcp",
}

HOSTED_ALIASES: dict[str, tuple[str, ...]] = {
    "exa": ("exa-mcp",),
    "firecrawl": ("firecrawl-mcp",),
    "hunter": ("hunter-mcp",),
    "indeed": ("indeed-mcp",),
    "google-workspace": ("gmail-mcp", "google-drive-mcp", "google-calendar-mcp"),
    "playwright": ("playwright-mcp",),
    "apollo": ("apollo-people",),
    "parallel-search": ("parallel-search-mcp",),
    "tavily": ("tavily-mcp",),
}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def alias_slug(key: str) -> str:
    text = str(key or "").strip().lower()
    if not text:
        return ""
    if text in EXAMPLE_ALIASES:
        return EXAMPLE_ALIASES[text]
    if text.endswith("-mcp"):
        return text
    return f"{text}-mcp"


def list_item_to_fields(raw: dict[str, Any], *, status: str, origin_ref: str) -> dict[str, Any] | None:
    kind = str(raw.get("kind") or "mcp").strip().lower()
    if kind in SKIP_KINDS:
        return None
    if kind not in MCP_KINDS:
        return None
    slug = str(raw.get("id") or raw.get("slug") or "").strip().lower()
    name = str(raw.get("name") or slug).strip()
    if not slug or not name:
        return None
    verdict = str(raw.get("verdict") or "").strip()
    if not verdict:
        if status == "adopted":
            verdict = "use"
        elif status == "wanted":
            verdict = "fork"
        else:
            verdict = "reject"
    fields = {
        "slug": slug,
        "name": name,
        "kind": kind,
        "status": status,
        "verdict": verdict,
        "capability": _as_list(raw.get("capability")),
        "roles": _as_list(raw.get("roles")),
        "platforms": _as_list(raw.get("platforms")),
        "source": str(raw.get("source") or "").strip(),
        "install": str(raw.get("install") or "").strip(),
        "auth": str(raw.get("auth") or "").strip(),
        "notes": str(raw.get("notes") or "").strip(),
        "reason": str(raw.get("reason") or "").strip(),
        "next_action": str(raw.get("next_action") or "").strip(),
        "config": {},
        "hosted": "",
        "origin": "github",
        "origin_ref": origin_ref,
    }
    fields["content_hash"] = content_hash_for(fields)
    return fields


def iter_list_mcps(repo_root: Path) -> list[dict[str, Any]]:
    lists_dir = repo_root / "skills" / "lists"
    out: list[dict[str, Any]] = []
    if not lists_dir.is_dir():
        return out
    seen: set[str] = set()
    for filename, status in LIST_FILES:
        path = lists_dir / filename
        if not path.is_file():
            continue
        payload = _load_yaml(path)
        items = payload.get("items") or []
        if not isinstance(items, list):
            continue
        origin_ref = path.relative_to(repo_root).as_posix()
        for raw in items:
            if not isinstance(raw, dict):
                continue
            fields = list_item_to_fields(raw, status=status, origin_ref=origin_ref)
            if fields is None:
                continue
            slug = fields["slug"]
            if slug in seen:
                continue
            seen.add(slug)
            out.append(fields)
    return out


def iter_example_servers(repo_root: Path) -> dict[str, dict[str, Any]]:
    path = repo_root / "mcp" / "mcp.example.json"
    if not path.is_file():
        return {}
    payload = _load_json(path)
    servers = payload.get("mcpServers") or payload
    if not isinstance(servers, dict):
        return {}
    origin_ref = path.relative_to(repo_root).as_posix()
    out: dict[str, dict[str, Any]] = {}
    for key, config in servers.items():
        if not isinstance(config, dict):
            continue
        slug = alias_slug(str(key))
        if not slug:
            continue
        out[slug] = {
            "example_key": str(key),
            "config": config,
            "origin_ref": origin_ref,
        }
    return out


def iter_hosted_paths(repo_root: Path) -> dict[str, str]:
    hosted_dir = repo_root / "mcp" / "hosted"
    out: dict[str, str] = {}
    if not hosted_dir.is_dir():
        return out
    for path in sorted(hosted_dir.glob("*.json")):
        stem = path.stem.lower()
        rel = f"/api/mcp/hosted/{path.name}"
        for slug in HOSTED_ALIASES.get(stem, (alias_slug(stem),)):
            out[slug] = rel
        payload = _load_json(path)
        for key in payload:
            if isinstance(payload.get(key), dict):
                out[alias_slug(str(key))] = rel
    return out


def merge_example_and_hosted(
    rows: list[dict[str, Any]],
    *,
    examples: dict[str, dict[str, Any]],
    hosted: dict[str, str],
) -> list[dict[str, Any]]:
    by_slug = {row["slug"]: dict(row) for row in rows}
    for slug, extra in examples.items():
        if slug in by_slug:
            by_slug[slug]["config"] = extra.get("config") or {}
            refs = [by_slug[slug].get("origin_ref") or "", extra.get("origin_ref") or ""]
            by_slug[slug]["origin_ref"] = ", ".join(r for r in refs if r)
            if not by_slug[slug].get("install"):
                config = extra.get("config") or {}
                url = config.get("url")
                if isinstance(url, str) and url:
                    by_slug[slug]["install"] = url
        else:
            config = extra.get("config") or {}
            name = str(extra.get("example_key") or slug)
            by_slug[slug] = {
                "slug": slug,
                "name": name,
                "kind": "mcp",
                "status": "adopted",
                "verdict": "use",
                "capability": [],
                "roles": [],
                "platforms": [],
                "source": extra.get("origin_ref") or "mcp/mcp.example.json",
                "install": str(config.get("url") or ""),
                "auth": "",
                "notes": "Seeded from mcp.example.json (not yet in skills/lists).",
                "reason": "",
                "next_action": "",
                "config": config,
                "hosted": "",
                "origin": "github",
                "origin_ref": extra.get("origin_ref") or "mcp/mcp.example.json",
            }
    for slug, hosted_url in hosted.items():
        if slug in by_slug:
            by_slug[slug]["hosted"] = hosted_url
        else:
            by_slug[slug] = {
                "slug": slug,
                "name": slug,
                "kind": "mcp",
                "status": "adopted",
                "verdict": "use",
                "capability": [],
                "roles": [],
                "platforms": [],
                "source": hosted_url,
                "install": "",
                "auth": "",
                "notes": "Seeded from mcp/hosted/.",
                "reason": "",
                "next_action": "",
                "config": {},
                "hosted": hosted_url,
                "origin": "github",
                "origin_ref": hosted_url.lstrip("/api/"),
            }
    out: list[dict[str, Any]] = []
    for row in by_slug.values():
        row["content_hash"] = content_hash_for(row)
        out.append(row)
    out.sort(key=lambda item: (item.get("status") or "", item.get("slug") or ""))
    return out


def iter_github_mcps(repo_root: Path) -> list[dict[str, Any]]:
    rows = iter_list_mcps(repo_root)
    examples = iter_example_servers(repo_root)
    hosted = iter_hosted_paths(repo_root)
    return merge_example_and_hosted(rows, examples=examples, hosted=hosted)


def repo_root_from_db(db: Any, settings: Settings | None = None) -> Path:
    if settings is not None:
        return repo_root_for(settings)
    board_dir = db.db_path.parent
    if board_dir.name == "data":
        board_dir = board_dir.parent
    return default_repo_root(board_dir)


def seed_github_mcps(
    db: Any,
    repo_root: Path | None = None,
    *,
    settings: Settings | None = None,
) -> dict[str, int]:
    root = repo_root or repo_root_from_db(db, settings)
    store = McpStore(db)
    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    for fields in iter_github_mcps(root):
        _row, action = store.upsert_github(fields)
        counts[action] = counts.get(action, 0) + 1
    return counts
