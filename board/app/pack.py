"""Immutable skill/MCP/docs pack. Git authors; Hub serves snapshots. No secrets."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.bootstrap import public_base
from app.constants import TRACKS, canonical_track
from app.profile import public_candidate_at, public_candidate_for_settings
from app.settings import Settings

PACK_VERSION = "1"
CURRENT_NAME = "CURRENT"
TREE_NAME = "tree"
CATALOG_DATE_RE = re.compile(r"Last catalog pass[:\s\*]*(\d{4}-\d{2}-\d{2})")
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9._-]+$")

FORBIDDEN_BASENAMES = frozenset(
    {
        ".env",
        "tokens.local.json",
        "candidate.yaml",
        "board.db",
        "metrics.sqlite",
    }
)

ALLOWED_SCRIPTS = (
    "install_agent_skills.sh",
    "link_agent_skills.sh",
    "setup_uv.sh",
    "setup_vendor_mcps.sh",
    "setup_deep_research.sh",
)

TRACK_SKILLS: dict[str, tuple[str, ...]] = {
    "discovery": ("skill-and-mcp-catalog", "job-discovery", "deep-research"),
    "application": ("job-apply", "deep-research"),
    "outreach": ("job-outreach", "deep-research"),
    "maintenance": ("skill-maintainer", "skill-and-mcp-catalog"),
}

TRACK_READINGS: dict[str, tuple[str, ...]] = {
    "discovery": (
        "AGENTS.md",
        "docs/process.md",
        "docs/roles.md",
        "docs/job-hub/memory.md",
        "docs/catalogs/skills-and-mcps.md",
        "docs/catalogs/skill-outline.md",
        "handoffs/apply-packet.md",
    ),
    "application": (
        "AGENTS.md",
        "docs/process.md",
        "docs/roles.md",
        "docs/job-hub/memory.md",
        "docs/catalogs/skill-outline.md",
        "handoffs/apply-packet.md",
    ),
    "outreach": (
        "AGENTS.md",
        "docs/process.md",
        "docs/roles.md",
        "docs/job-hub/memory.md",
        "docs/catalogs/skill-outline.md",
        "handoffs/outreach-packet.md",
    ),
    "maintenance": (
        "AGENTS.md",
        "docs/process.md",
        "docs/roles.md",
        "docs/job-hub/memory.md",
        "docs/catalogs/skills-and-mcps.md",
        "docs/catalogs/skill-outline.md",
        "skills/lists/INDEX.md",
    ),
}

TRACK_PROCESS: dict[str, dict[str, Any]] = {
    "discovery": {
        "must_read": ["process.md#discovery-cycle", "roles.md#discovery-owner"],
        "forbidden": [
            "Easy Apply",
            "form submit",
            "send outreach",
            "invent candidate",
        ],
        "channels_default": ["email", "linkedin_dm"],
        "catalog_first": True,
    },
    "application": {
        "must_read": ["process.md#apply-cycle", "roles.md#apply-owner"],
        "forbidden": ["invent jobs", "cold outreach", "skip packet"],
        "channels_default": ["email", "linkedin_dm"],
        "catalog_first": False,
    },
    "outreach": {
        "must_read": ["process.md#outreach-cycle", "roles.md#outreach-owner"],
        "forbidden": ["SMS", "WhatsApp", "InMail sequences", "apply", "attach nothing"],
        "channels_default": ["email", "linkedin_dm"],
        "catalog_first": False,
    },
    "maintenance": {
        "must_read": ["roles.md#maintainer", "process.md#catalog-pass"],
        "forbidden": [
            "discover jobs",
            "Easy Apply",
            "submit applications",
            "send outreach",
            "put secrets in lists or git",
        ],
        "channels_default": ["email", "linkedin_dm"],
        "catalog_first": True,
    },
}

TRACK_QUEUES: dict[str, list[str]] = {
    "discovery": ["discovery.search"],
    "application": ["apply.ready"],
    "outreach": ["outreach.ready"],
    "maintenance": ["skill.record", "catalog.refresh"],
}

# Names and instructions only. Never secret values.
CONNECTOR_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "gmail",
        "required_on": ("outreach",),
        "reason": "Outreach drafts with resume PDF attachments (Gmail MCP).",
        "auth_url": "https://gmailmcp.googleapis.com/mcp/v1",
        "env_fallback": "GMAIL_*",
        "hosted": "/api/mcp/hosted/google-workspace.json",
    },
    {
        "id": "google_drive",
        "required_on": (),
        "reason": "Optional Drive access for resume/docs the Hub does not store in YAML.",
        "auth_url": "https://drivemcp.googleapis.com/mcp/v1",
        "env_fallback": "GOOGLE_DRIVE_*",
        "hosted": "/api/mcp/hosted/google-workspace.json",
    },
    {
        "id": "google_calendar",
        "required_on": ("outreach",),
        "reason": "Optional interview scheduling; never a Hub login.",
        "auth_url": "https://calendarmcp.googleapis.com/mcp/v1",
        "env_fallback": "GOOGLE_CALENDAR_*",
        "hosted": "/api/mcp/hosted/google-workspace.json",
    },
    {
        "id": "indeed",
        "required_on": ("discovery",),
        "reason": "Discovery search via official Indeed MCP when the operator has OAuth.",
        "auth_url": "https://mcp.indeed.com/claude/mcp",
        "env_fallback": "INDEED_*",
        "hosted": "/api/mcp/hosted/indeed.json",
    },
    {
        "id": "exa",
        "required_on": ("discovery", "application", "outreach", "maintenance"),
        "reason": "Deep research / web fetch. Agent local env key; Hub never returns the value.",
        "auth_url": "https://mcp.exa.ai/mcp",
        "env_fallback": "EXA_API_KEY",
        "hosted": "/api/mcp/hosted/exa.json",
    },
)


@dataclass(frozen=True)
class PackMeta:
    pack_sha: str
    git_sha: str
    built_at: str
    catalog_updated_at: str | None
    files: int


def default_repo_root(board_dir: Path) -> Path:
    parent = board_dir.parent
    if (parent / "skills" / "job-discovery" / "SKILL.md").is_file():
        return parent
    here = Path(__file__).resolve().parents[2]
    if (here / "skills" / "job-discovery" / "SKILL.md").is_file():
        return here
    return parent


def packs_dir_for(settings: Settings) -> Path:
    if settings.packs_dir is not None:
        return Path(settings.packs_dir)
    return Path(settings.board_dir) / "data" / "packs"


def repo_root_for(settings: Settings) -> Path:
    if settings.repo_root is not None:
        return Path(settings.repo_root)
    return default_repo_root(Path(settings.board_dir))


def git_sha_for(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            timeout=5,
            stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_relpath(raw: str) -> str | None:
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip().replace("\\", "/")
    if not text or text.startswith("/") or ":" in text:
        return None
    if "\x00" in text:
        return None
    collapsed = posixpath.normpath(text)
    if collapsed in {".", ""} or collapsed.startswith("../") or collapsed == "..":
        return None
    if collapsed.startswith("/"):
        return None
    parts = collapsed.split("/")
    if any(p in {"", ".", ".."} for p in parts):
        return None
    if any(p.startswith(".") and p not in {"."} and p.endswith(".env") for p in parts):
        return None
    if any(p in FORBIDDEN_BASENAMES for p in parts):
        return None
    return collapsed


def is_allowlisted_relpath(rel: str) -> bool:
    if rel in {"AGENTS.md", "skills-lock.json", "mcp/mcp.example.json"}:
        return True
    if rel.startswith("docs/") and not rel.endswith("/"):
        return True
    if rel.startswith("handoffs/") and not rel.endswith("/"):
        return True
    if rel.startswith("skills/") and not rel.endswith("/"):
        return True
    if rel.startswith("mcp/hosted/") and rel.endswith(".json"):
        name = Path(rel).name
        return bool(SAFE_FILE_RE.match(name))
    if rel.startswith("scripts/") and rel.count("/") == 1:
        return Path(rel).name in ALLOWED_SCRIPTS
    return False


def connectors_for_track(track: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in CONNECTOR_CATALOG:
        item = {
            "id": row["id"],
            "required": track in row["required_on"],
            "reason": row["reason"],
            "auth_url": row["auth_url"],
            "env_fallback": row["env_fallback"],
            "hosted": row["hosted"],
        }
        out.append(item)
    return out


def catalog_updated_at(repo_root: Path) -> str | None:
    path = repo_root / "docs" / "catalogs" / "skills-and-mcps.md"
    if not path.is_file():
        return None
    match = CATALOG_DATE_RE.search(path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _unquote(raw: str) -> str:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _block_list(section: str, key: str) -> list[str]:
    match = re.search(rf"^  {re.escape(key)}:\n((?:    - .*\n)*)", section, re.M)
    if not match:
        return []
    items: list[str] = []
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(_unquote(stripped[2:]))
    return items


def _scalar_in_section(section: str, key: str) -> str | None:
    match = re.search(rf"^  {re.escape(key)}:\s*(.+)\s*$", section, re.M)
    if not match:
        return None
    return _unquote(match.group(1))


def public_candidate(repo_root: Path) -> dict[str, Any]:
    hub = repo_root / "data" / "profiles" / "candidate.yaml"
    repo = repo_root / "profiles" / "candidate.yaml"
    if hub.is_file():
        return public_candidate_at(hub)
    return public_candidate_at(repo if repo.is_file() else None)


def skills_on_disk(repo_root: Path) -> list[str]:
    root = repo_root / "skills"
    if not root.is_dir():
        return []
    names = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and SKILL_NAME_RE.match(child.name) and (child / "SKILL.md").is_file():
            names.append(child.name)
    return names


def iter_source_files(repo_root: Path) -> Iterable[Path]:
    candidates: list[Path] = [
        repo_root / "AGENTS.md",
        repo_root / "skills-lock.json",
        repo_root / "mcp" / "mcp.example.json",
    ]
    for folder in ("docs", "handoffs", "skills"):
        base = repo_root / folder
        if base.is_dir():
            candidates.extend(p for p in base.rglob("*") if p.is_file())
    hosted = repo_root / "mcp" / "hosted"
    if hosted.is_dir():
        candidates.extend(p for p in hosted.glob("*.json") if p.is_file())
    for name in ALLOWED_SCRIPTS:
        candidates.append(repo_root / "scripts" / name)
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            rel = path.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        if not is_allowlisted_relpath(rel):
            continue
        if path.name in FORBIDDEN_BASENAMES:
            continue
        yield path


def _install_md(repo_root: Path, track: str) -> str:
    skills = TRACK_SKILLS.get(track, ())
    lines = [
        f"# Job Hub pack install ({track})",
        "",
        "Consumers do **not** clone the hunt repo. Copy these trees into your agent skills dir",
        " (`.cursor/skills`, `.claude/skills`, or `.agents/skills`).",
        "",
        "Track skills in this zip:",
        *[f"- `{name}/`" for name in skills],
        "",
        "Also fetch:",
        "- `GET /api/mcp/example.json`",
        "- `GET /api/mcp/hosted/{name}.json`",
        "- `GET /api/scripts/install_agent_skills.sh`",
        "",
        "Fill MCP env keys only in **local gitignored** files. Never write secrets to the ledger.",
        "",
        "Marketplace pins (`npx skills add …`); not vendored unless already in the operator checkout:",
    ]
    lock_path = repo_root / "skills-lock.json"
    if lock_path.is_file():
        try:
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
            pinned = payload.get("skills") if isinstance(payload, dict) else {}
            if isinstance(pinned, dict):
                for name, meta in pinned.items():
                    source = ""
                    if isinstance(meta, dict):
                        source = str(meta.get("source") or "")
                    if source:
                        lines.append(f"- `{name}`: `npx skills add {source} --skill {name} -y`")
                    else:
                        lines.append(f"- `{name}`")
        except json.JSONDecodeError:
            lines.append("- (skills-lock.json unreadable)")
    lines.append("")
    return "\n".join(lines)


class PackStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.repo_root = repo_root_for(settings)
        self.packs_dir = packs_dir_for(settings)

    def current_sha(self) -> str:
        pointer = self.packs_dir / CURRENT_NAME
        if pointer.is_file():
            return pointer.read_text(encoding="utf-8").strip()
        return ""

    def current_dir(self) -> Path | None:
        sha = self.current_sha()
        if not sha:
            return None
        path = self.packs_dir / sha
        return path if path.is_dir() else None

    def meta(self) -> PackMeta:
        self.ensure_current()
        current = self.current_dir()
        if current is None:
            return PackMeta("", git_sha_for(self.repo_root), "", catalog_updated_at(self.repo_root), 0)
        manifest_path = current / "manifest.json"
        if manifest_path.is_file():
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return PackMeta(
                pack_sha=str(data.get("pack_sha") or current.name),
                git_sha=str(data.get("git_sha") or ""),
                built_at=str(data.get("built_at") or ""),
                catalog_updated_at=data.get("catalog_updated_at"),
                files=int(data.get("files") or 0),
            )
        return PackMeta(current.name, git_sha_for(self.repo_root), "", catalog_updated_at(self.repo_root), 0)

    def ensure_current(self) -> PackMeta:
        current = self.current_dir()
        if current is not None and (current / "manifest.json").is_file():
            return self.meta_without_ensure()
        return self.rebuild()

    def meta_without_ensure(self) -> PackMeta:
        current = self.current_dir()
        if current is None:
            return PackMeta("", git_sha_for(self.repo_root), "", catalog_updated_at(self.repo_root), 0)
        manifest_path = current / "manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        return PackMeta(
            pack_sha=str(data.get("pack_sha") or current.name),
            git_sha=str(data.get("git_sha") or ""),
            built_at=str(data.get("built_at") or ""),
            catalog_updated_at=data.get("catalog_updated_at"),
            files=int(data.get("files") or 0),
        )

    def rebuild(self) -> PackMeta:
        self.packs_dir.mkdir(parents=True, exist_ok=True)
        staging = self.packs_dir / f".staging-{utc_stamp().replace(':', '')}"
        tree = staging / TREE_NAME
        tree.mkdir(parents=True)
        entries: list[dict[str, str]] = []
        for src in iter_source_files(self.repo_root):
            rel = src.relative_to(self.repo_root).as_posix()
            dest = tree / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            digest = sha256_file(dest)
            entries.append({"path": rel, "sha256": digest})
        entries.sort(key=lambda row: row["path"])
        hasher = hashlib.sha256()
        git_sha = git_sha_for(self.repo_root)
        hasher.update(git_sha.encode("utf-8"))
        for row in entries:
            hasher.update(row["path"].encode("utf-8"))
            hasher.update(b"\n")
            hasher.update(row["sha256"].encode("utf-8"))
            hasher.update(b"\n")
        pack_sha = hasher.hexdigest()[:40]
        catalog = catalog_updated_at(self.repo_root)
        built_at = utc_stamp()
        manifest = {
            "pack_sha": pack_sha,
            "git_sha": git_sha,
            "built_at": built_at,
            "catalog_updated_at": catalog,
            "files": len(entries),
            "entries": entries,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        for track in TRACKS:
            self._write_track_zip(staging, tree, track)
        final = self.packs_dir / pack_sha
        if final.exists():
            shutil.rmtree(staging)
        else:
            staging.rename(final)
        (self.packs_dir / CURRENT_NAME).write_text(pack_sha + "\n", encoding="utf-8")
        return PackMeta(pack_sha, git_sha, built_at, catalog, len(entries))

    def _write_track_zip(self, staging: Path, tree: Path, track: str) -> None:
        zip_path = staging / f"skills-{track}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("INSTALL.md", _install_md(self.repo_root, track))
            for name in TRACK_SKILLS.get(track, ()):
                skill_root = tree / "skills" / name
                if not skill_root.is_dir():
                    continue
                for path in skill_root.rglob("*"):
                    if not path.is_file():
                        continue
                    arc = path.relative_to(tree).as_posix()
                    zf.write(path, arcname=arc)

    def tree_file(self, rel: str) -> Path | None:
        self.ensure_current()
        current = self.current_dir()
        if current is None:
            return None
        safe = normalize_relpath(rel)
        if safe is None or not is_allowlisted_relpath(safe):
            return None
        path = (current / TREE_NAME / safe).resolve()
        tree = (current / TREE_NAME).resolve()
        if tree not in path.parents and path != tree:
            return None
        if not path.is_file():
            return None
        return path

    def zip_path(self, track: str) -> Path | None:
        self.ensure_current()
        current = self.current_dir()
        if current is None:
            return None
        key = canonical_track(track) or track
        path = current / f"skills-{key}.zip"
        return path if path.is_file() else None

    def reading_entries(self, track: str) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for rel in TRACK_READINGS.get(track, ()):
            path = self.tree_file(rel)
            digest = sha256_file(path) if path else ""
            out.append(
                {
                    "path": rel,
                    "url": f"/api/docs/{rel}",
                    "sha256": digest,
                }
            )
        return out

    def skill_entries(self, track: str) -> list[dict[str, Any]]:
        names = TRACK_SKILLS.get(track, ())
        out: list[dict[str, Any]] = []
        for name in names:
            files = [f"/api/skills/{name}/SKILL.md"]
            path = self.tree_file(f"skills/{name}/SKILL.md")
            if path is None:
                continue
            skill_dir = path.parent
            extra = []
            for child in sorted(skill_dir.rglob("*")):
                if child.is_file() and child.name != "SKILL.md":
                    rel = child.relative_to(skill_dir).as_posix()
                    extra.append(f"/api/skills/{name}/{rel}")
            files.extend(extra)
            out.append({"name": name, "files": files})
        return out

    def script_entries(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for name in ALLOWED_SCRIPTS:
            if self.tree_file(f"scripts/{name}") is not None:
                out.append({"name": name, "url": f"/api/scripts/{name}"})
        return out

    def onboarding_payload(self, track: str) -> dict[str, Any]:
        key = canonical_track(track) or "discovery"
        if key not in TRACK_SKILLS:
            key = "discovery"
        meta = self.ensure_current()
        return {
            "hub": {
                "public_url": public_base(self.settings),
                "version": PACK_VERSION,
                "git_sha": meta.git_sha,
                "pack_sha": meta.pack_sha,
                "built_at": meta.built_at,
            },
            "track": key,
            "process": dict(TRACK_PROCESS[key]),
            "readings": self.reading_entries(key),
            "skills": self.skill_entries(key),
            "skills_zip": "/api/packs/current/skills.zip",
            "mcp_example": "/api/mcp/example.json",
            "scripts": self.script_entries(),
            "connectors_needed": connectors_for_track(key),
            "heartbeat_s": 10,
            "memory": {
                "recall": "/api/memory/recall",
                "write": "/api/memory/items",
                "solidify": "/api/memory/items/{id}/solidify",
                "pods": "/api/memory/pods",
                "docs": "/api/docs/docs/job-hub/memory.md",
                "use_every_round": True,
                "store_sparingly": True,
            },
            "queues": list(TRACK_QUEUES.get(key, [])),
            "candidate": public_candidate_for_settings(self.settings),
            "catalog_updated_at": meta.catalog_updated_at,
            "registry": "/api/registry/skills",
            "pack": {
                "git_sha": meta.git_sha,
                "pack_sha": meta.pack_sha,
                "built_at": meta.built_at,
                "files": meta.files,
            },
        }


def join_onboarding_section(settings: Settings, invite: dict[str, Any]) -> dict[str, Any]:
    store = PackStore(settings)
    meta = store.ensure_current()
    track = invite.get("track") or "discovery"
    return {
        "available": True,
        "url": "/api/onboarding",
        "invite_query": ["invite_id", "s"],
        "skills_zip": "/api/packs/current/skills.zip",
        "mcp_example": "/api/mcp/example.json",
        "docs": "/api/docs/{path}",
        "skills": "/api/skills/{name}/{file}",
        "registry": "/api/registry/skills",
        "scripts": "/api/scripts/{name}",
        "hosted_mcp": "/api/mcp/hosted/{name}.json",
        "pack_sha": meta.pack_sha,
        "git_sha": meta.git_sha,
        "catalog_updated_at": meta.catalog_updated_at,
        "track": track,
        "note": "GET /api/onboarding?invite_id=&s= (or Authorization after join). Do not clone the hunt repo.",
    }


def hub_pack_fields(settings: Settings) -> dict[str, str]:
    store = PackStore(settings)
    meta = store.ensure_current()
    return {
        "pack_sha": meta.pack_sha,
        "git_sha": meta.git_sha,
        "built_at": meta.built_at,
    }


def skill_allowed(track: str, name: str, *, unrestricted: bool) -> bool:
    if not SKILL_NAME_RE.match(name or ""):
        return False
    if unrestricted:
        return True
    return name in TRACK_SKILLS.get(track, ())
