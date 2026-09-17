"""Candidate profile persistence, public slice, and onboarding validation.

Never invent a live candidate. The example profile is rejected as production data.
Stored next to the Hub sqlite file so Docker `/data` volumes keep it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from app.settings import Settings

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


def public_candidate_for_settings(settings: Settings) -> dict[str, Any]:
    path = resolve_candidate_path(settings)
    payload = public_candidate_at(path)
    if path is not None and path == hub_candidate_path(settings):
        payload["source"] = "hub-data"
    elif path is not None:
        payload["source"] = "repo"
    else:
        payload["source"] = "missing"
    resume = resolve_resume_path(settings)
    payload["resume_url"] = "/api/candidate/resume" if resume else None
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


def candidate_status(settings: Settings) -> dict[str, Any]:
    path = resolve_candidate_path(settings)
    resume = resolve_resume_path(settings)
    missing: list[str] = ["profiles/candidate.yaml"]
    onboarded = False
    present = False
    if path is not None and path.is_file():
        present = True
        try:
            data = normalize_profile(load_profile_dict(path))
            missing = validate_profile(data)
            onboarded = not missing
        except (OSError, yaml.YAMLError, ValueError):
            missing = ["unreadable_candidate_yaml"]
            onboarded = False
    ready = onboarded and resume is not None
    if onboarded and resume is None:
        next_step = "resume"
    elif not onboarded:
        next_step = "onboarding"
    else:
        next_step = "ready"
    return {
        "present": present,
        "onboarded": onboarded,
        "resume_present": resume is not None,
        "ready_for_agents": ready,
        "missing": missing,
        "onboarding_url": "/onboarding",
        "next_step": next_step,
        "source": "hub-data"
        if path == hub_candidate_path(settings)
        else ("repo" if path else "missing"),
    }


def candidate_onboarded(settings: Settings) -> bool:
    return bool(candidate_status(settings)["onboarded"])
