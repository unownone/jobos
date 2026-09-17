"""Candidate profile persistence, public slice, and onboarding validation.

Never invent a live candidate. The example profile is rejected as production data.
Stored in Postgres `hub_blobs` so Hub containers stay stateless.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from app.settings import Settings

CANDIDATE_BLOB_KEY = "candidate.yaml"
RESUME_BLOB_KEY = "candidate-resume.pdf"

_blob_store: Any | None = None


def bind_blob_store(store: Any | None) -> None:
    global _blob_store
    _blob_store = store


def blob_store() -> Any | None:
    return _blob_store

CANDIDATE_PUBLIC_FIELDS = [
    "target.titles",
    "target.locations",
    "target.deal_breakers",
    "identity.work_authorization",
]

EXAMPLE_NAMES = frozenset({"ada example"})
EXAMPLE_EMAILS = frozenset({"ada@example.com"})

REQUIRED_IDENTITY = ("full_name", "email")
REQUIRED_TARGET_LISTS = ("titles", "locations")

EMPTY_TEMPLATE: dict[str, Any] = {
    "identity": {
        "full_name": "",
        "preferred_name": "",
        "email": "",
        "phone": "",
        "location": "",
        "timezone": "",
        "work_authorization": "",
        "linkedin_url": "",
        "github_url": "",
        "portfolio_url": "",
        "website": "",
    },
    "target": {
        "titles": [],
        "seniority": [],
        "domains": [],
        "locations": [],
        "remote": "",
        "salary_floor_usd": 0,
        "visa_needs": False,
        "company_sizes": [],
        "must_haves": [],
        "deal_breakers": [],
    },
    "proof": {
        "headline": "",
        "years_experience": 0,
        "stack": [],
        "highlights": [],
        "do_not_claim": [],
    },
    "materials": {
        "resume_primary": "assets/resume/resume-primary.pdf",
        "resume_variants": [],
        "writing_voice": "",
    },
    "constraints": {
        "max_discovers_per_cycle": 40,
        "max_shortlist_per_cycle": 12,
        "max_applies_per_day": 8,
        "max_outreach_touches_per_person": 2,
        "easy_apply_policy": "never during discovery; apply role may use it only after a packet exists",
    },
}


def data_dir(settings: Settings) -> Path:
    return settings.db_path.parent


def hub_candidate_path(settings: Settings) -> Path:
    return data_dir(settings) / "profiles" / "candidate.yaml"


def hub_resume_path(settings: Settings) -> Path:
    return data_dir(settings) / "candidate-resume.pdf"


def repo_candidate_path(settings: Settings) -> Path:
    root = settings.repo_root or settings.board_dir.parent
    return root / "profiles" / "candidate.yaml"


def repo_resume_dir(settings: Settings) -> Path:
    root = settings.repo_root or settings.board_dir.parent
    return root / "assets" / "resume"


def _as_bytes(content: Any) -> bytes:
    if isinstance(content, memoryview):
        return content.tobytes()
    if isinstance(content, bytearray):
        return bytes(content)
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    return bytes(content)


def _store(db: Any | None) -> Any | None:
    return db if db is not None else _blob_store


def candidate_blob_text(db: Any | None = None) -> str | None:
    store = _store(db)
    if store is None:
        return None
    blob = store.get_blob(CANDIDATE_BLOB_KEY)
    if not blob or not blob.get("content"):
        return None
    return _as_bytes(blob["content"]).decode("utf-8")


def resume_blob_bytes(db: Any | None = None) -> bytes | None:
    store = _store(db)
    if store is None:
        return None
    blob = store.get_blob(RESUME_BLOB_KEY)
    if not blob or not blob.get("content"):
        return None
    return _as_bytes(blob["content"])


def write_candidate_yaml(settings: Settings, text: str, db: Any | None = None) -> None:
    store = _store(db)
    if store is None:
        raise RuntimeError("Hub database is required to store the candidate profile")
    store.put_blob(
        CANDIDATE_BLOB_KEY,
        text.encode("utf-8"),
        content_type="text/yaml",
        filename="candidate.yaml",
    )
    dest = hub_candidate_path(settings)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")


def write_resume_pdf(settings: Settings, raw: bytes, db: Any | None = None) -> None:
    store = _store(db)
    if store is None:
        raise RuntimeError("Hub database is required to store the resume PDF")
    store.put_blob(
        RESUME_BLOB_KEY,
        raw,
        content_type="application/pdf",
        filename="candidate-resume.pdf",
    )
    dest = hub_resume_path(settings)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)


def resolve_candidate_path(settings: Settings) -> Path | None:
    local = hub_candidate_path(settings)
    if local.is_file():
        return local
    repo = repo_candidate_path(settings)
    if repo.is_file():
        return repo
    return None


def resolve_resume_path(settings: Settings) -> Path | None:
    local = hub_resume_path(settings)
    if local.is_file():
        return local
    assets = repo_resume_dir(settings)
    if assets.is_dir():
        pdfs = sorted(assets.glob("*.pdf"))
        if pdfs:
            return pdfs[0]
    return None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace("\n", ",").split(",")]
        return [p for p in parts if p]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    text = str(value).strip()
    return [text] if text else []


def public_slice_from_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Public Candidate Profile fields from a parsed mapping. No regex."""
    identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    target = data.get("target") if isinstance(data.get("target"), dict) else {}
    auth = identity.get("work_authorization")
    auth_text = str(auth).strip() if auth is not None else ""
    return {
        "present": True,
        "fields_public": list(CANDIDATE_PUBLIC_FIELDS),
        "target": {
            "titles": _as_list(target.get("titles")),
            "locations": _as_list(target.get("locations")),
            "deal_breakers": _as_list(target.get("deal_breakers")),
        },
        "work_authorization": auth_text or None,
        "resume_url": None,
    }


def public_slice_from_text(text: str) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError:
        raw = None
    if not isinstance(raw, dict):
        return {
            "present": True,
            "fields_public": list(CANDIDATE_PUBLIC_FIELDS),
            "target": {"titles": [], "locations": [], "deal_breakers": []},
            "work_authorization": None,
            "resume_url": None,
        }
    return public_slice_from_mapping(raw)


def public_candidate_at(path: Path | None) -> dict[str, Any]:
    base = {"present": False, "fields_public": list(CANDIDATE_PUBLIC_FIELDS)}
    if path is None or not path.is_file():
        return base
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {**base, "present": True}
    if not text.strip():
        return base
    return public_slice_from_text(text)


def candidate_revision(settings: Settings, db: Any | None = None) -> str | None:
    """Bump when postgres blob or hub/repo candidate file bytes change. Agents must re-fetch."""
    path = resolve_candidate_path(settings)
    if path is not None and path.is_file():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        mtime = int(path.stat().st_mtime)
        return f"{mtime}-{digest}"
    text = candidate_blob_text(db)
    if text is not None and text.strip():
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return f"postgres-{digest}"
    return None


def public_candidate_for_settings(settings: Settings, db: Any | None = None) -> dict[str, Any]:
    path = resolve_candidate_path(settings)
    text = candidate_blob_text(db)
    if path is not None and path.is_file():
        payload = public_candidate_at(path)
        if path == hub_candidate_path(settings):
            payload["source"] = "postgres"
        else:
            payload["source"] = "repo"
    elif text is not None and text.strip():
        payload = public_slice_from_text(text)
        payload["source"] = "postgres"
    else:
        payload = public_candidate_at(None)
        payload["source"] = "missing"
    resume = resume_blob_bytes(db) is not None or resolve_resume_path(settings) is not None
    payload["resume_url"] = "/api/candidate/resume" if resume else None
    payload["revision"] = candidate_revision(settings, db)
    return payload


def load_profile_dict(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    return raw


def normalize_profile(data: dict[str, Any]) -> dict[str, Any]:
    identity_in = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    target_in = data.get("target") if isinstance(data.get("target"), dict) else {}
    proof_in = data.get("proof") if isinstance(data.get("proof"), dict) else {}
    materials_in = data.get("materials") if isinstance(data.get("materials"), dict) else {}
    constraints_in = data.get("constraints") if isinstance(data.get("constraints"), dict) else {}

    identity = dict(EMPTY_TEMPLATE["identity"])
    for key, value in identity_in.items():
        if key in identity:
            identity[key] = "" if value is None else value
    target = dict(EMPTY_TEMPLATE["target"])
    for key, value in target_in.items():
        if key in {"titles", "seniority", "domains", "locations", "company_sizes", "must_haves", "deal_breakers"}:
            target[key] = _as_list(value)
        elif key in target:
            target[key] = value
    proof = dict(EMPTY_TEMPLATE["proof"])
    for key, value in proof_in.items():
        if key in {"stack", "highlights", "do_not_claim"}:
            proof[key] = _as_list(value)
        elif key in proof:
            proof[key] = value
    materials = dict(EMPTY_TEMPLATE["materials"])
    for key, value in materials_in.items():
        if key == "resume_variants":
            materials[key] = _as_list(value)
        elif key in materials:
            materials[key] = value
    constraints = dict(EMPTY_TEMPLATE["constraints"])
    for key, value in constraints_in.items():
        if key in constraints:
            constraints[key] = value
    return {
        "identity": identity,
        "target": target,
        "proof": proof,
        "materials": materials,
        "constraints": constraints,
    }


def validate_profile(data: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    target = data.get("target") if isinstance(data.get("target"), dict) else {}
    for key in REQUIRED_IDENTITY:
        value = str(identity.get(key) or "").strip()
        if not value:
            missing.append(f"identity.{key}")
    for key in REQUIRED_TARGET_LISTS:
        if not _as_list(target.get(key)):
            missing.append(f"target.{key}")
    name = str(identity.get("full_name") or "").strip().lower()
    email = str(identity.get("email") or "").strip().lower()
    if name in EXAMPLE_NAMES or email in EXAMPLE_EMAILS:
        missing.append("example_profile_not_allowed")
    if email and "@" not in email:
        missing.append("identity.email")
    return missing


def dump_profile_yaml(data: dict[str, Any]) -> str:
    normalized = normalize_profile(data)
    header = (
        "# Live candidate profile. Gitignored. Do not invent experience.\n"
        "# Filled via Hub /onboarding or PUT /api/candidate.\n\n"
    )
    body = yaml.safe_dump(
        normalized,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    return header + body


def parse_candidate_body(raw: bytes, content_type: str) -> dict[str, Any]:
    text = raw.decode("utf-8")
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in {"application/json", "text/json"}:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("candidate JSON must be an object")
        return normalize_profile(payload)
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ValueError("candidate YAML must be a mapping")
    return normalize_profile(loaded)


def candidate_status(settings: Settings, db: Any | None = None) -> dict[str, Any]:
    text = candidate_blob_text(db)
    path = resolve_candidate_path(settings)
    resume = resume_blob_bytes(db)
    resume_present = resume is not None or resolve_resume_path(settings) is not None
    missing: list[str] = ["profiles/candidate.yaml"]
    onboarded = False
    present = False
    source = "missing"
    if text is not None and text.strip():
        present = True
        source = "postgres"
        try:
            loaded = yaml.safe_load(text)
            data = normalize_profile(loaded if isinstance(loaded, dict) else {})
            missing = validate_profile(data)
            onboarded = not missing
        except (yaml.YAMLError, ValueError):
            missing = ["unreadable_candidate_yaml"]
            onboarded = False
    elif path is not None and path.is_file():
        present = True
        source = "postgres" if path == hub_candidate_path(settings) else "repo"
        try:
            data = normalize_profile(load_profile_dict(path))
            missing = validate_profile(data)
            onboarded = not missing
        except (OSError, yaml.YAMLError, ValueError):
            missing = ["unreadable_candidate_yaml"]
            onboarded = False
    ready = onboarded and resume_present
    if onboarded and not resume_present:
        next_step = "resume"
    elif not onboarded:
        next_step = "onboarding"
    else:
        next_step = "ready"
    return {
        "present": present,
        "onboarded": onboarded,
        "resume_present": resume_present,
        "ready_for_agents": ready,
        "missing": missing,
        "onboarding_url": "/onboarding",
        "next_step": next_step,
        "source": source,
        "revision": candidate_revision(settings, db),
    }


def candidate_onboarded(settings: Settings) -> bool:
    return bool(candidate_status(settings)["onboarded"])
