"""Write gates for Hub memory pods. Recall freely; store only durable facts."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from app.constants import TRACKS, canonical_track

POD_COMMON = "common"
POD_KIND_WORKER = "worker"
POD_KIND_TRACK = "track"
POD_KIND_COMMON = "common"

KINDS_WORKER = frozenset({"working_note", "reminder", "fact"})
KINDS_TRACK = frozenset(
    {
        "portal_quirk",
        "blocker",
        "tool_failure",
        "company_note",
        "process_note",
        "person_hint",
        "search_coverage",
    }
)
KINDS_COMMON = frozenset(
    {
        "process_note",
        "tool_failure",
        "catalog_note",
        "candidate_constraint",
        "hub_note",
    }
)

WRITE_WINDOW_S = 15 * 60
WRITE_CAPS = {
    POD_KIND_WORKER: 6,
    POD_KIND_TRACK: 3,
    POD_KIND_COMMON: 2,
}

TITLE_MIN = 8
TITLE_MAX = 120
BODY_MAX = 800
BODY_MIN = {
    "working_note": 24,
    "reminder": 24,
    "default": 40,
}
WORKER_TTL_DAYS = 7
LOW_IMPORTANCE_TTL_DAYS = 30
MAX_NEWLINES = 8
COMPACT_BODY_CHARS = 240
HEARTBEAT_LIMIT = 6
RECALL_LIMIT_DEFAULT = 12
RECALL_LIMIT_MAX = 24

SECRET_PREFIXES = ("jh_agt_", "jh_own_", "jh_inv_", "jh_boot_", "jh_adm_", "sk-", "xox")
SECRET_PHRASES = (
    "api_key",
    "apikey",
    "board_token",
    "hub_key",
    "private_key",
    "authorization: bearer",
    "bearer jh_",
)
SECRET_WORD_RE = re.compile(
    r"\b(password|passwd|secret|cookie|api-key|apikey)\b",
    re.I,
)
DUMP_MARKERS = (
    "transcript",
    "as an ai",
    "here is the full",
    "paste of the jd",
    "job description follows",
)

_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")
_SLUG_RE = re.compile(r"[^a-z0-9._-]+")
_TRACK_ALIASES = {
    "applicator": "application",
    "apply": "application",
    "maintainer": "maintenance",
    "mainainer": "maintenance",
}


class MemoryError(Exception):
    status_code = 400
    code = "memory_error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class MemoryDenied(MemoryError):
    status_code = 403
    code = "memory_forbidden"


class MemoryInvalid(MemoryError):
    status_code = 422
    code = "memory_invalid"


class MemoryNotFound(MemoryError):
    status_code = 404
    code = "memory_not_found"


class MemoryRateLimited(MemoryError):
    status_code = 429
    code = "memory_rate_limited"


def is_hub_admin(principal: Any) -> bool:
    return getattr(principal, "kind", None) == "admin" or getattr(principal, "role", None) == "admin"


def is_inspector(principal: Any) -> bool:
    if is_hub_admin(principal):
        return True
    if getattr(principal, "role", None) == "maintenance":
        return True
    return getattr(principal, "track", None) == "maintenance"


def resolve_track(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip().lower()
    aliased = _TRACK_ALIASES.get(key, key)
    return canonical_track(aliased) or (aliased if aliased in TRACKS else None)


def worker_id(principal: Any) -> str:
    user_id = getattr(principal, "user_id", None)
    if user_id:
        return str(user_id)
    actor = (getattr(principal, "actor", None) or "anon").strip() or "anon"
    slug = _SLUG_RE.sub("-", actor.lower()).strip("-")[:40] or "anon"
    role = getattr(principal, "role", None) or "unknown"
    return f"compat:{role}:{slug}"


def worker_pod_id(principal: Any) -> str:
    return f"{POD_KIND_WORKER}:{worker_id(principal)}"


def track_pod_id(track: str) -> str:
    resolved = resolve_track(track)
    if resolved is None:
        raise MemoryInvalid("unknown track for memory pod")
    return f"{POD_KIND_TRACK}:{resolved}"


def own_track_pod_id(principal: Any) -> str | None:
    track = getattr(principal, "track", None)
    if not track:
        return None
    return f"{POD_KIND_TRACK}:{track}"


def parse_pod(raw: str) -> tuple[str, str | None]:
    text = (raw or "").strip().lower()
    if not text:
        raise MemoryInvalid("pod is required")
    if text in {"common", "shared", "global"}:
        return POD_KIND_COMMON, None
    if text in {"worker", "self", "me"}:
        return POD_KIND_WORKER, None
    if text in {"track", "lane"}:
        return POD_KIND_TRACK, None
    mapped = resolve_track(text)
    if mapped:
        return POD_KIND_TRACK, mapped
    if text.startswith("worker:"):
        ident = text.split(":", 1)[1].strip()
        if not ident:
            raise MemoryInvalid("worker pod needs an id")
        return POD_KIND_WORKER, ident
    if text.startswith("track:"):
        ident = resolve_track(text.split(":", 1)[1])
        if ident is None:
            raise MemoryInvalid("unknown track pod")
        return POD_KIND_TRACK, ident
    if text.startswith("common:"):
        return POD_KIND_COMMON, None
    raise MemoryInvalid("pod must be worker, track, common, or track:<name>")


def resolve_write_pod(principal: Any, raw: str | None) -> str:
    kind, ident = parse_pod(raw or "worker")
    if kind == POD_KIND_COMMON:
        return POD_COMMON
    if kind == POD_KIND_WORKER:
        own = worker_pod_id(principal)
        if ident is None or ident in {"self", "me"}:
            return own
        target = f"{POD_KIND_WORKER}:{ident}"
        if target != own:
            raise MemoryDenied("cannot write another worker's private pod")
        return own
    # track
    own_track = getattr(principal, "track", None)
    target_track = ident or own_track
    if target_track is None:
        raise MemoryInvalid("this principal has no track pod; use worker or common")
    resolved = resolve_track(target_track)
    if resolved is None:
        raise MemoryInvalid("unknown track for memory pod")
    if not is_hub_admin(principal) and resolved != own_track:
        raise MemoryDenied("cannot write another track's shared pod")
    return f"{POD_KIND_TRACK}:{resolved}"


def resolve_read_pod(principal: Any, raw: str) -> str:
    kind, ident = parse_pod(raw)
    if kind == POD_KIND_COMMON:
        return POD_COMMON
    if kind == POD_KIND_WORKER:
        own = worker_pod_id(principal)
        if ident is None or ident in {"self", "me"}:
            return own
        target = f"{POD_KIND_WORKER}:{ident}"
        if target != own and not is_inspector(principal):
            raise MemoryDenied("cannot read another worker's private pod")
        return target
    own_track = getattr(principal, "track", None)
    target_track = ident or own_track
    if target_track is None and not is_inspector(principal):
        raise MemoryInvalid("track pod required")
    resolved = resolve_track(target_track) if target_track else None
    if resolved is None:
        raise MemoryInvalid("unknown track for memory pod")
    if not is_inspector(principal) and resolved != own_track:
        raise MemoryDenied("cannot read another track's shared pod")
    return f"{POD_KIND_TRACK}:{resolved}"


def visible_pod_ids(principal: Any) -> list[str]:
    pods = [worker_pod_id(principal), POD_COMMON]
    own = own_track_pod_id(principal)
    if own:
        pods.insert(1, own)
    if is_inspector(principal):
        for track in TRACKS:
            pod = f"{POD_KIND_TRACK}:{track}"
            if pod not in pods:
                pods.append(pod)
    return pods


def can_read_pod(principal: Any, pod: str) -> bool:
    if pod == POD_COMMON:
        return True
    if pod == worker_pod_id(principal):
        return True
    own = own_track_pod_id(principal)
    if own and pod == own:
        return True
    return is_inspector(principal)


def pod_scope(pod: str) -> str:
    if pod == POD_COMMON or pod.startswith("common"):
        return POD_KIND_COMMON
    if pod.startswith("track:"):
        return POD_KIND_TRACK
    if pod.startswith("worker:"):
        return POD_KIND_WORKER
    raise MemoryInvalid("unknown pod")


def kinds_for_scope(scope: str) -> frozenset[str]:
    if scope == POD_KIND_WORKER:
        return KINDS_WORKER
    if scope == POD_KIND_TRACK:
        return KINDS_TRACK
    if scope == POD_KIND_COMMON:
        return KINDS_COMMON
    raise MemoryInvalid("unknown pod scope")


def looks_secret(text: str) -> bool:
    lowered = text.lower()
    if any(prefix in lowered for prefix in SECRET_PREFIXES):
        return True
    if any(phrase in lowered for phrase in SECRET_PHRASES):
        return True
    return bool(SECRET_WORD_RE.search(text))


def validate_kind(scope: str, kind: str) -> str:
    key = (kind or "").strip().lower()
    allowed = kinds_for_scope(scope)
    if key not in allowed:
        raise MemoryInvalid(f"kind {key!r} is not allowed on the {scope} pod")
    return key


def _min_body(kind: str) -> int:
    return BODY_MIN.get(kind, BODY_MIN["default"])


def validate_write_text(*, kind: str, scope: str, title: str, body: str) -> tuple[str, str]:
    title_text = _WS_RE.sub(" ", (title or "").strip())
    body_text = (body or "").strip()
    if len(title_text) < TITLE_MIN or len(title_text) > TITLE_MAX:
        raise MemoryInvalid(f"title must be {TITLE_MIN}–{TITLE_MAX} characters")
    min_body = _min_body(kind)
    if len(body_text) < min_body:
        raise MemoryInvalid(
            f"body is too short to be a durable fact (need ≥{min_body} chars). "
            "Do not store chatter; skip the write."
        )
    if len(body_text) > BODY_MAX:
        raise MemoryInvalid(f"body must be ≤{BODY_MAX} characters; distill the fact")
    if looks_secret(title_text) or looks_secret(body_text):
        raise MemoryInvalid("memory cannot store secrets, tokens, or credentials")
    stripped = body_text.lstrip()
    if stripped[:1] in "{[":
        raise MemoryInvalid("do not store JSON dumps or transcripts; write one distilled fact")
    if body_text.count("\n") > MAX_NEWLINES:
        raise MemoryInvalid("too many lines; distill to one short fact")
    lowered = f"{title_text}\n{body_text}".lower()
    if any(marker in lowered for marker in DUMP_MARKERS):
        raise MemoryInvalid("that looks like a transcript/dump; do not store it")
    if scope != POD_KIND_WORKER and kind == "working_note":
        raise MemoryInvalid("working_note is worker-pod only")
    return title_text, body_text


def content_hash(
    *,
    kind: str,
    title: str,
    body: str,
    company: str | None,
    job_id: str | None,
) -> str:
    norm = "\n".join(
        [
            kind.strip().lower(),
            _WS_RE.sub(" ", title.strip().lower()),
            _WS_RE.sub(" ", body.strip().lower()),
            (company or "").strip().lower(),
            (job_id or "").strip().lower(),
        ]
    )
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def default_ttl_days(*, scope: str, kind: str, importance: int) -> int | None:
    if scope == POD_KIND_WORKER:
        return WORKER_TTL_DAYS
    if importance <= 1:
        return LOW_IMPORTANCE_TTL_DAYS
    if kind in {"working_note", "reminder"}:
        return WORKER_TTL_DAYS
    return None


def clamp_importance(raw: int | None) -> int:
    value = 2 if raw is None else int(raw)
    if value < 1 or value > 3:
        raise MemoryInvalid("importance must be 1, 2, or 3")
    return value


def fts_match_query(raw: str | None) -> str | None:
    if not raw:
        return None
    tokens = _TOKEN_RE.findall(raw)[:8]
    if not tokens:
        return None
    return " AND ".join(f'"{tok}"' for tok in tokens)


def compact_body(body: str, limit: int = COMPACT_BODY_CHARS) -> str:
    text = _WS_RE.sub(" ", (body or "").strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def write_budget_hint() -> dict[str, Any]:
    return {
        "window_s": WRITE_WINDOW_S,
        "caps": dict(WRITE_CAPS),
        "store_when": "A fact that would help another bot tomorrow (portal quirk, blocker, dead tool, search coverage).",
        "do_not_store": [
            "transcripts",
            "job-description dumps",
            "secrets or tokens",
            "every search hit",
            "opinions without evidence",
        ],
        "per_round": "0–2 track/common writes. Worker notes only for your own next loop.",
    }
