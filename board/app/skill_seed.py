"""Parse GitHub starter skills and write them into the Hub registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.pack import default_repo_root, repo_root_for
from app.skill_store import SkillStore, _normalize_match, content_hash_for
from app.settings import Settings
from app.tenant import COMPAT_ACCOUNT_ID, TenantContext

ROLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "job-discovery": {
        "role": "discovery",
        "tags": ["source"],
        "inputs": ["candidate", "platforms"],
        "outputs": ["job", "apply_packet"],
    },
    "job-apply": {
        "role": "apply",
        "tags": ["apply"],
        "inputs": ["job", "apply_packet", "candidate"],
        "outputs": ["proof", "outreach_packet"],
    },
    "job-outreach": {
        "role": "outreach",
        "tags": ["outreach"],
        "inputs": ["job", "outreach_packet", "candidate"],
        "outputs": ["touches"],
    },
    "deep-research": {
        "role": "research",
        "tags": ["research"],
        "inputs": ["job", "url"],
        "outputs": ["research"],
    },
    "skill-maintainer": {
        "role": "maintain",
        "tags": ["maintain"],
        "inputs": ["registry", "lists"],
        "outputs": ["skills_lists"],
    },
    "skill-and-mcp-catalog": {
        "role": "maintain",
        "tags": ["maintain", "source"],
        "inputs": ["catalog"],
        "outputs": ["skills_and_mcps"],
    },
    "agent-session": {
        "role": "agent",
        "tags": ["agent"],
        "inputs": ["session"],
        "outputs": ["lanes", "loop"],
    },
}

SKIP_SKILL_DIRS = frozenset({"lists", "starters"})


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    raw = text.lstrip("\ufeff")
    if not raw.startswith("---"):
        return {}, raw.strip()
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}, raw.strip()
    try:
        front = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        front = {}
    if not isinstance(front, dict):
        front = {}
    body = parts[2].strip()
    return front, body


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def starter_to_fields(raw: dict[str, Any], *, origin_ref: str, slug_fallback: str) -> dict[str, Any] | None:
    slug = str(raw.get("slug") or raw.get("name") or slug_fallback).strip().lower()
    name = str(raw.get("name") or slug).strip()
    body = str(raw.get("body") or raw.get("body_md") or "").strip()
    role = str(raw.get("role") or "").strip()
    tags = _as_list(raw.get("tags"))
    if not slug or not name or not body or not role or not tags:
        return None
    defaults = ROLE_DEFAULTS.get(slug, {})
    if not tags:
        tags = list(defaults.get("tags") or [])
    fields = {
        "slug": slug,
        "name": name,
        "kind": str(raw.get("kind") or "skill"),
        "role": role or str(defaults.get("role") or "discovery"),
        "tags": tags,
        "platform": str(raw.get("platform") or "").strip(),
        "match": raw.get("match") or {"ats": [], "url_patterns": [], "apply_kind": []},
        "inputs": _as_list(raw.get("inputs") or defaults.get("inputs")),
        "outputs": _as_list(raw.get("outputs") or defaults.get("outputs")),
        "body": body,
        "origin": "github",
        "origin_ref": origin_ref,
        "reproducible": bool(raw.get("reproducible", True)),
        "created_by": "github",
    }
    try:
        fields["match"] = _normalize_match(fields["match"])
    except Exception:
        fields["match"] = {"ats": [], "url_patterns": [], "apply_kind": []}
    fields["content_hash"] = content_hash_for(body, slug, fields["role"], tags)
    return fields


def parse_skill_md(path: Path, *, repo_root: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8")
    front, body = split_frontmatter(text)
    slug = path.parent.name
    defaults = ROLE_DEFAULTS.get(slug, {})
    merged = {
        "slug": front.get("slug") or slug,
        "name": front.get("name") or slug,
        "kind": front.get("kind") or "skill",
        "role": front.get("role") or defaults.get("role"),
        "tags": front.get("tags") or defaults.get("tags") or [],
        "platform": front.get("platform") or "",
        "match": front.get("match") or {},
        "inputs": front.get("inputs") or defaults.get("inputs") or [],
        "outputs": front.get("outputs") or defaults.get("outputs") or [],
        "reproducible": front.get("reproducible", True),
        "body": body or text.strip(),
    }
    origin_ref = path.relative_to(repo_root).as_posix()
    return starter_to_fields(merged, origin_ref=origin_ref, slug_fallback=slug)


def parse_starter_yaml(path: Path, *, repo_root: Path) -> dict[str, Any] | None:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    origin_ref = path.relative_to(repo_root).as_posix()
    return starter_to_fields(raw, origin_ref=origin_ref, slug_fallback=path.stem)


def _role_from_list(roles: Any) -> str:
    mapped = {
        "discovery": "discovery",
        "apply": "apply",
        "outreach": "outreach",
        "maintainer": "maintain",
        "maintain": "maintain",
        "research": "research",
        "agent": "agent",
    }
    items = _as_list(roles)
    for item in items:
        key = item.strip().lower()
        if key in mapped:
            return mapped[key]
    if "all" in [item.strip().lower() for item in items]:
        return "research"
    return ""


def _skill_md_from_source(repo_root: Path, source: str) -> Path | None:
    text = (source or "").strip()
    if not text or "://" in text:
        return None
    path = (repo_root / text).resolve()
    try:
        path.relative_to(repo_root.resolve())
    except ValueError:
        return None
    if path.is_dir():
        candidate = path / "SKILL.md"
        return candidate if candidate.is_file() else None
    if path.is_file() and path.suffix.lower() in {".md", ".markdown"}:
        return path
    return None


def parse_adopted_skill(raw: dict[str, Any], *, repo_root: Path) -> dict[str, Any] | None:
    """Approved shared SKILL.md that lives in-repo (including .agents/skills)."""
    if str(raw.get("kind") or "skill").strip().lower() != "skill":
        return None
    source_path = _skill_md_from_source(repo_root, str(raw.get("source") or ""))
    if source_path is None:
        return None
    parsed = parse_skill_md(source_path, repo_root=repo_root)
    if parsed is not None:
        return parsed
    text = source_path.read_text(encoding="utf-8")
    front, body = split_frontmatter(text)
    slug = str(raw.get("id") or front.get("slug") or source_path.parent.name).strip().lower()
    tags = _as_list(front.get("tags") or raw.get("capability"))
    if not tags:
        role_guess = _role_from_list(raw.get("roles"))
        tags = [role_guess] if role_guess else ["research"]
    merged = {
        "slug": slug,
        "name": front.get("name") or raw.get("name") or slug,
        "kind": "skill",
        "role": front.get("role") or _role_from_list(raw.get("roles")),
        "tags": tags,
        "platform": front.get("platform") or "",
        "match": front.get("match") or {},
        "inputs": front.get("inputs") or [],
        "outputs": front.get("outputs") or [],
        "reproducible": front.get("reproducible", True),
        "body": body or text.strip(),
    }
    origin_ref = source_path.relative_to(repo_root).as_posix()
    return starter_to_fields(merged, origin_ref=origin_ref, slug_fallback=slug)


def iter_adopted_shared_skills(repo_root: Path) -> list[dict[str, Any]]:
    path = repo_root / "skills" / "lists" / "adopted.yaml"
    if not path.is_file():
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return []
    items = payload.get("items") or []
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        parsed = parse_adopted_skill(raw, repo_root=repo_root)
        if parsed:
            out.append(parsed)
    return out


def iter_github_starters(repo_root: Path) -> list[dict[str, Any]]:
    skills_dir = repo_root / "skills"
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    if not skills_dir.is_dir():
        return out
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir() or child.name in SKIP_SKILL_DIRS or child.name.startswith("."):
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        parsed = parse_skill_md(skill_md, repo_root=repo_root)
        if parsed:
            out.append(parsed)
            seen.add(parsed["slug"])
    starters = skills_dir / "starters"
    if starters.is_dir():
        for path in sorted(starters.glob("*.yaml")):
            parsed = parse_starter_yaml(path, repo_root=repo_root)
            if parsed:
                out.append(parsed)
                seen.add(parsed["slug"])
        for path in sorted(starters.glob("*.yml")):
            parsed = parse_starter_yaml(path, repo_root=repo_root)
            if parsed:
                out.append(parsed)
                seen.add(parsed["slug"])
    for parsed in iter_adopted_shared_skills(repo_root):
        if parsed["slug"] in seen:
            continue
        out.append(parsed)
        seen.add(parsed["slug"])
    return out


def repo_root_from_db(db: Any, settings: Settings | None = None) -> Path:
    if settings is not None:
        return repo_root_for(settings)
    board_dir = db.db_path.parent
    if board_dir.name == "data":
        board_dir = board_dir.parent
    return default_repo_root(board_dir)


def seed_github_skills(
    db: Any,
    repo_root: Path | None = None,
    *,
    settings: Settings | None = None,
    tenant: Any | None = None,
) -> dict[str, int]:
    root = repo_root or repo_root_from_db(db, settings)
    store = SkillStore(db, tenant or TenantContext(COMPAT_ACCOUNT_ID))
    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    for fields in iter_github_starters(root):
        _skill, action = store.upsert_github(fields)
        counts[action] = counts.get(action, 0) + 1
    return counts
