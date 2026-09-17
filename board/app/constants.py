"""Status enum and role write surfaces. Statuses match ledger/schema/job.schema.json."""

from __future__ import annotations

ROLES = (
    "discovery",
    "apply",
    "outreach",
    "admin",
    "maintenance",
)

# Hub API track names. Process role `apply` / `maintainer` are aliases.
TRACKS = (
    "discovery",
    "application",
    "outreach",
    "maintenance",
)

# Documented stubs. Not invite tracks. Not owners. Do not claim.
COMING_SOON_ROLES = (
    {
        "id": "review",
        "name": "review",
        "status": "coming_soon",
        "summary": "Will review the candidate profile/resume and give feedback on shortlisted jobs.",
    },
    {
        "id": "resume",
        "name": "resume",
        "status": "coming_soon",
        "summary": "Will tailor ATS-friendly resumes from the candidate profile.",
    },
)

TRACK_ALIASES = {
    "discovery": "discovery",
    "application": "application",
    "apply": "application",
    "applicator": "application",
    "outreach": "outreach",
    "maintenance": "maintenance",
    "maintainer": "maintenance",
}

TRACK_TO_ROLE = {
    "discovery": "discovery",
    "application": "apply",
    "outreach": "outreach",
    "maintenance": "maintenance",
}

ROLE_TO_TRACK = {
    "discovery": "discovery",
    "apply": "application",
    "outreach": "outreach",
    "maintenance": "maintenance",
    "admin": None,
}

INVITE_MODES = (
    "owner_then_agents",
    "agents_only",
    "owner_only",
)

USER_KINDS = (
    "admin",
    "viewer",
    "owner",
    "agent",
)

METADATA_KNOWN_KEYS = (
    "model",
    "harness",
    "bed",
    "provider",
    "runtime",
    "version",
    "capabilities",
    "notes",
)

STATUSES = (
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
)

DISCOVERY_LANE = frozenset(
    {
        "discovered",
        "enriching",
        "shortlisted",
        "skipped",
        "apply_ready",
    }
)

APPLY_LANE = frozenset(
    {
        "apply_ready",
        "applying",
        "applied",
        "apply_blocked",
        "outreach_ready",
        "closed_expired",
    }
)

OUTREACH_LANE = frozenset(
    {
        "applied",
        "outreach_ready",
        "outreaching",
        "waiting",
        "chatting",
        "interview",
        "offer",
        "closed_rejected",
        "closed_withdrawn",
    }
)

# Identity / discovery-owned. Apply and outreach must not rewrite these.
IDENTITY_FIELDS = frozenset(
    {
        "company",
        "title",
        "location",
        "remote",
        "url",
        "apply_url",
        "apply_kind",
        "ats",
        "req_id",
        "sources",
    }
)

DISCOVERY_FIELDS = IDENTITY_FIELDS | {
    "id",
    "status",
    "score",
    "owners",
    "apply_packet",
    "research",
    "notes",
    "conflicts",
}

APPLY_FIELDS = frozenset(
    {
        "status",
        "owners",
        "proof",
        "outreach_packet",
        "notes",
    }
)

OUTREACH_FIELDS = frozenset(
    {
        "status",
        "owners",
        "outreach_packet",
        "notes",
    }
)

ADMIN_FIELDS = DISCOVERY_FIELDS | APPLY_FIELDS | {
    "stopped",
    "stop_reason",
    "research",
    "proof",
    "conflicts",
}

JSON_FIELDS = frozenset(
    {
        "sources",
        "owners",
        "apply_packet",
        "outreach_packet",
        "research",
        "proof",
        "conflicts",
    }
)

TOKEN_ENV = {
    "discovery": "BOARD_TOKEN_DISCOVERY",
    "apply": "BOARD_TOKEN_APPLY",
    "outreach": "BOARD_TOKEN_OUTREACH",
    "admin": "BOARD_TOKEN_ADMIN",
    "maintenance": "BOARD_TOKEN_MAINTENANCE",
}

def canonical_track(value: str | None) -> str | None:
    if value is None:
        return None
    key = value.strip().lower()
    return TRACK_ALIASES.get(key)


def role_for_track(track: str | None) -> str | None:
    if not track:
        return None
    return TRACK_TO_ROLE.get(track)


CREATE_ROLES = frozenset({"discovery", "admin"})
STOP_ROLES = frozenset({"admin"})
DELETE_ROLES = frozenset({"admin"})
HYGIENE_ROLES = frozenset({"admin", "maintenance"})
IMPORT_ROLES = frozenset({"admin", "maintenance"})
EXPORT_ROLES = IMPORT_ROLES
METRICS_READ_ROLES = frozenset({"admin", "maintenance"})
PATCH_ROLES = frozenset({"discovery", "apply", "outreach", "admin"})
PEOPLE_ROLES = frozenset({"outreach", "admin"})
RESUME_ROLES = frozenset({"apply", "outreach", "admin"})
