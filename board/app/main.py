"""FastAPI Job Hub (hunt board). Maintainer-owned. Bind 0.0.0.0 so sibling agents can reach it."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app.auth import Principal, optional_principal, require_admin, require_owner_or_admin, require_principal
from app.a2a import create_a2a_router
from app.bootstrap import (
    consume_bootstrap,
    ensure_bootstrap,
    env_path_for,
    format_signup_line,
    sha256_hex,
    tokens_json_path_for,
    verify_password,
)
from app.candidate import create_candidate_router
from app.gates import CandidateGateMiddleware
from app.constants import METADATA_KNOWN_KEYS, ROLES, STATUSES, TRACKS
from app.db import BoardDB, public_user
from app.export import create_export_router
from app.identity import (
    COOKIE_SESSION,
    clear_session_cookies,
    create_invite,
    create_user_session,
    disable_agent,
    invite_status_error,
    join_payload,
    join_url,
    join_with_invite,
    mint_agent_for_owner,
    parse_invite_token,
    public_invite,
    rotate_user_key,
    set_session_cookies,
    verify_invite_secret,
)
from app.messages import create_messages_router
from app.metrics import MetricsStore
from app.onboarding import create_onboarding_router
from app.pack import PackStore
from app.people import create_people_router
from app.permissions import (
    authorize_create,
    authorize_patch,
    capabilities,
    ensure_can_delete,
    ensure_can_hygiene,
    ensure_can_import,
    ensure_can_read_metrics,
    ensure_can_stop,
    validate_status,
)
from app.profile import candidate_onboarded, candidate_status
from app.presence import mount_presence
from app.queue import QUEUE_KINDS, QueueService, register_queue_routes
from app.settings import Settings, load_settings

STATIC_DIR = Path(__file__).resolve().parent / "static"
ID_RE = re.compile(r"^[a-z0-9]+__[a-zA-Z0-9._-]+$")
SLUG_RE = re.compile(r"[^a-z0-9]+")


class JobIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    company: str
    title: str
    location: str | None = None
    remote: str | bool | None = None
    url: str | None = None
    apply_url: str | None = None
    apply_kind: str | None = None
    ats: str | None = None
    req_id: str | None = None
    sources: list[str] | None = None
    status: str | None = "discovered"
    score: float | None = None
    owners: dict[str, str] | None = None
    apply_packet: dict[str, Any] | None = None
    outreach_packet: dict[str, Any] | None = None
    research: dict[str, Any] | None = None
    proof: dict[str, Any] | None = None
    notes: str | None = None
    conflicts: list[Any] | None = None
    stopped: bool | None = None
    stop_reason: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class JobPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str | None = None
    title: str | None = None
    location: str | None = None
    remote: str | bool | None = None
    url: str | None = None
    apply_url: str | None = None
    apply_kind: str | None = None
    ats: str | None = None
    req_id: str | None = None
    sources: list[str] | None = None
    status: str | None = None
    score: float | None = None
    owners: dict[str, str] | None = None
    apply_packet: dict[str, Any] | None = None
    outreach_packet: dict[str, Any] | None = None
    research: dict[str, Any] | None = None
    proof: dict[str, Any] | None = None
    notes: str | None = None
    conflicts: list[Any] | None = None
    stopped: bool | None = None
    stop_reason: str | None = None


class StopIn(BaseModel):
    reason: str = Field(min_length=1)


class PauseIn(BaseModel):
    reason: str = Field(min_length=1)


class TokenBurnIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    tool_name: str = Field(min_length=1)
    skill: str | None = None
    lane: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int | None = None
    cost_usd: float | None = None
    duration_ms: float | None = None
    job_id: str | None = None
    timestamp: str | None = None
    extra: dict[str, Any] | None = None


class ImportIn(BaseModel):
    jobs: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    replace: bool = False


class BootstrapIn(BaseModel):
    email: str
    password: str
    token: str | None = None
    bootstrap: str | None = None


def _slug_id(company: str, title: str) -> str:
    slug = SLUG_RE.sub("-", f"{company}-{title}".lower()).strip("-")[:72]
    return f"board__{slug or 'job'}"


def _normalize_id(raw: str) -> str:
    job_id = raw.strip()
    if not ID_RE.match(job_id):
        raise HTTPException(
            status_code=422,
            detail="id must match {source}__{stable_id} (ledger schema)",
        )
    return job_id


class LoginIn(BaseModel):
    email: str
    password: str


class InviteIn(BaseModel):
    track: str
    max_redemptions: int | None = 8
    ttl_hours: float | None = 72
    mode: str | None = "owner_then_agents"
    allow_multiple_owners: bool = False


class JoinIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    invite_id: str | None = None
    s: str | None = None
    secret: str | None = None
    token: str | None = None
    display_name: str
    metadata: dict[str, Any] | None = None
    model: str | None = None
    harness: str | None = None
    bed: str | None = None
    provider: str | None = None
    capabilities: list[str] | Any | None = None


class AgentIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    display_name: str
    track: str | None = None
    metadata: dict[str, Any] | None = None
    model: str | None = None
    harness: str | None = None
    bed: str | None = None
    provider: str | None = None
    capabilities: list[str] | Any | None = None


def _merge_signup_metadata(body: JoinIn | AgentIn) -> dict[str, Any]:
    meta = dict(body.metadata or {})
    for key in METADATA_KNOWN_KEYS:
        value = getattr(body, key, None)
        if value is not None and key not in meta:
            meta[key] = value
    extra = body.model_dump(exclude_none=True)
    skip = {
        "invite_id",
        "s",
        "secret",
        "token",
        "display_name",
        "metadata",
        "track",
    }
    for key, value in extra.items():
        if key not in skip and key not in meta:
            meta[key] = value
    return meta


def _extract_bootstrap_token(request: Request, body: BootstrapIn) -> str:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    for header in ("x-hub-key", "x-bootstrap-token"):
        value = request.headers.get(header)
        if value:
            return value.strip()
    return (body.token or body.bootstrap or "").strip()


def _health_payload(db: BoardDB, settings: Settings) -> dict[str, Any]:
    configured = sorted(role for role, token in settings.tokens.items() if token)
    bootstrapped = db.admin_bootstrapped()
    cand = candidate_status(settings)
    if not bootstrapped:
        next_step = "signup"
    elif not cand["onboarded"]:
        next_step = "onboarding"
    elif not cand["resume_present"]:
        next_step = "resume"
    else:
        next_step = "ready"
    return {
        "ok": True,
        "roles_configured": configured,
        "all_roles_configured": configured == sorted(ROLES),
        "admin_bootstrapped": bootstrapped,
        "candidate_onboarded": cand["onboarded"],
        "resume_present": cand["resume_present"],
        "ready_for_agents": cand["ready_for_agents"] and bootstrapped,
        "next_step": next_step,
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    db = BoardDB(settings.db_path)
    metrics = MetricsStore(
        settings.db_path.parent / "metrics.sqlite",
        settings.db_path.parent / "metrics.jsonl",
    )
    principal_dep = require_principal(settings, db)
    optional_principal_dep = optional_principal(settings, db)
    pack = PackStore(settings)
    pack.ensure_current()
    queue = QueueService(db, pack=pack)
    minted = ensure_bootstrap(settings, db)

    app = FastAPI(
        title="Job Hub",
        description="Private live coordination plane. Maintainer owns tokens, schema, and uptime.",
        version="0.5.0",
    )
    app.add_middleware(CandidateGateMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.db = db
    app.state.metrics = metrics
    app.state.queue = queue
    app.state.pack = pack
    app.state.bootstrap_token = minted
    register_queue_routes(app, queue=queue, principal_dep=principal_dep)
    app.include_router(create_messages_router(principal_dep))
    app.include_router(create_people_router(principal_dep))
    app.include_router(create_export_router(principal_dep))
    app.include_router(create_candidate_router(settings, principal_dep))
    app.include_router(create_a2a_router(settings, principal_dep, optional_principal_dep))
    if minted:
        print(format_signup_line(settings, minted), flush=True)
        print(
            "Gitignored secrets: "
            f"{env_path_for(settings)} {tokens_json_path_for(settings)}",
            flush=True,
        )

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    app.include_router(create_onboarding_router(settings, db, pack, principal_dep))

    @app.get("/", response_model=None)
    def index() -> FileResponse | RedirectResponse:
        if db.admin_bootstrapped() and not candidate_onboarded(settings):
            return RedirectResponse(url="/onboarding", status_code=302)
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/onboarding")
    def candidate_onboarding_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "onboarding.html")

    @app.get("/admin/signup", response_model=None)
    def admin_signup() -> FileResponse | RedirectResponse:
        if db.admin_bootstrapped():
            return RedirectResponse(url="/login", status_code=302)
        return FileResponse(STATIC_DIR / "signup.html")

    @app.get("/admin", response_model=None)
    def admin_home() -> FileResponse | RedirectResponse:
        if db.admin_bootstrapped():
            return FileResponse(STATIC_DIR / "admin.html")
        return RedirectResponse(url="/admin/signup", status_code=302)

    @app.get("/admin/invites")
    def admin_invites() -> FileResponse:
        if db.admin_bootstrapped():
            return FileResponse(STATIC_DIR / "admin.html")
        return FileResponse(STATIC_DIR / "signup.html")

    @app.get("/login")
    def login_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "login.html")

    @app.get("/join/{invite_id}")
    def join_page(invite_id: str) -> FileResponse:
        return FileResponse(STATIC_DIR / "join.html")

    @app.get("/favicon.ico")
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return _health_payload(db, settings)

    @app.get("/ready")
    def ready() -> dict[str, Any]:
        payload = _health_payload(db, settings)
        try:
            db.conn.execute("SELECT 1").fetchone()
            payload["db"] = True
        except Exception:
            payload["ok"] = False
            payload["db"] = False
        payload["ready"] = bool(payload["ok"] and payload["db"])
        return payload

    @app.post("/api/auth/bootstrap")
    def auth_bootstrap(request: Request, body: BootstrapIn) -> JSONResponse:
        token = _extract_bootstrap_token(request, body)
        if not token:
            raise HTTPException(status_code=401, detail="missing bootstrap token")
        try:
            result = consume_bootstrap(
                settings,
                db,
                token=token,
                email=body.email,
                password=body.password,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        user = result["user"]
        response = JSONResponse(
            {
                "ok": True,
                "admin_bootstrapped": True,
                "user": {
                    "id": user["id"],
                    "kind": user["kind"],
                    "email": user["email"],
                    "display_name": user["display_name"],
                },
            }
        )
        set_session_cookies(response, result["session_token"], result["csrf_token"])
        return response

    def _principal_payload(principal: Principal) -> dict[str, Any]:
        payload = {
            "role": principal.role,
            "actor": principal.actor,
            "user_id": principal.user_id,
            "track": principal.track,
            "kind": principal.kind,
            "auth": principal.auth,
            "compat": principal.auth == "compat_role",
            "compat_deprecated": principal.auth == "compat_role",
            **capabilities(principal.role),
        }
        if principal.user_id:
            user = db.get_user(principal.user_id)
            if user:
                payload["user"] = public_user(user)
        if principal.auth == "compat_role":
            payload["deprecation"] = (
                "X-Role + X-Token compat keys are deprecated; use Authorization: Bearer owner/agent keys"
            )
        return payload

    @app.post("/api/auth/login")
    def auth_login(body: LoginIn) -> JSONResponse:
        user = db.get_user_by_email(body.email)
        if user is None or not user.get("password_hash"):
            raise HTTPException(status_code=401, detail="invalid email or password")
        if user.get("disabled_at"):
            raise HTTPException(status_code=401, detail="user disabled")
        if not verify_password(user["password_hash"], body.password):
            raise HTTPException(status_code=401, detail="invalid email or password")
        session_token, csrf_token = create_user_session(db, user["id"])
        db.add_event(
            job_id=None,
            actor_role="admin",
            actor=user.get("email") or user["id"],
            action="login",
            fields={"user_id": user["id"]},
        )
        response = JSONResponse({"ok": True, "user": public_user(user)})
        set_session_cookies(response, session_token, csrf_token)
        return response

    @app.post("/api/auth/logout")
    def auth_logout(
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> JSONResponse:
        raw = request.cookies.get(COOKIE_SESSION) or ""
        if raw:
            sess = db.get_session_by_token_hash(sha256_hex(raw))
            if sess:
                db.delete_session(sess["id"])
        response = JSONResponse({"ok": True, "role": principal.role})
        clear_session_cookies(response)
        return response

    @app.get("/api/auth/me")
    def auth_me(principal: Principal = Depends(principal_dep)) -> dict[str, Any]:
        return _principal_payload(principal)

    @app.post("/api/invites")
    def create_invite_endpoint(
        body: InviteIn,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        require_admin(principal)
        row, secret = create_invite(
            db,
            track=body.track,
            mode=body.mode,
            max_redemptions=body.max_redemptions,
            ttl_hours=body.ttl_hours,
            allow_multiple_owners=body.allow_multiple_owners,
            created_by=principal.user_id or principal.actor,
        )
        url = join_url(settings, row["id"], secret)
        db.add_event(
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="invite_create",
            fields={"invite_id": row["id"], "track": row["track"], "mode": row["mode"]},
        )
        return {
            "invite": public_invite(row),
            "secret": secret,
            "join_url": url,
            "token": f"jh_inv_{row['id']}.{secret}",
            "shown_once": True,
        }

    @app.get("/api/invites")
    def list_invites_endpoint(principal: Principal = Depends(principal_dep)) -> dict[str, Any]:
        require_admin(principal)
        return {"invites": [public_invite(row) for row in db.list_invites()]}

    @app.post("/api/invites/{invite_id}/revoke")
    def revoke_invite_endpoint(
        invite_id: str,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        require_admin(principal)
        row = db.get_invite(invite_id)
        if row is None:
            raise HTTPException(status_code=404, detail="invite not found")
        stored = db.revoke_invite(invite_id)
        db.add_event(
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="invite_revoke",
            fields={"invite_id": invite_id},
        )
        return {"invite": public_invite(stored)}

    def _load_invite_for_join(invite_id: str, secret: str) -> dict[str, Any]:
        row = db.get_invite(invite_id)
        if row is None:
            raise HTTPException(status_code=404, detail="invite not found")
        if not verify_invite_secret(row, secret):
            raise HTTPException(status_code=401, detail="invalid invite secret")
        err = invite_status_error(row)
        if err:
            raise err
        return row

    @app.get("/api/join/{invite_id}")
    def join_payload_endpoint(invite_id: str, s: str | None = None) -> dict[str, Any]:
        if not s:
            raise HTTPException(status_code=401, detail="missing invite secret")
        row = _load_invite_for_join(invite_id, s)
        return join_payload(settings, row)

    @app.post("/api/auth/join")
    def auth_join(request: Request, body: JoinIn) -> dict[str, Any]:
        invite_id = (body.invite_id or "").strip()
        secret = (body.s or body.secret or "").strip()
        token = (body.token or "").strip()
        auth = request.headers.get("authorization") or ""
        if not token and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
        if token.startswith("jh_inv_"):
            parsed_id, parsed_secret = parse_invite_token(token)
            invite_id = invite_id or (parsed_id or "")
            secret = secret or (parsed_secret or "")
        if not invite_id or not secret:
            raise HTTPException(status_code=401, detail="missing invite_id or secret")
        return join_with_invite(
            db,
            invite_id=invite_id,
            secret=secret,
            display_name=body.display_name,
            metadata=_merge_signup_metadata(body),
        )

    @app.get("/api/agents")
    def list_agents(principal: Principal = Depends(principal_dep)) -> dict[str, Any]:
        require_owner_or_admin(principal)
        track = None if principal.kind == "admin" or principal.role == "admin" else principal.track
        users = db.list_users(track=track, kind="agent")
        if principal.kind == "admin" or principal.role == "admin":
            users = db.list_users(kind="agent") + db.list_users(kind="owner")
        return {"users": [public_user(u) for u in users]}

    @app.post("/api/agents")
    def create_agent(
        body: AgentIn,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        require_owner_or_admin(principal)
        if principal.kind == "agent":
            raise HTTPException(status_code=403, detail="agents cannot mint sibling agents")
        if principal.auth == "compat_role" and principal.role == "admin":
            actor = {
                "id": principal.actor or "compat-admin",
                "kind": "admin",
                "track": None,
                "display_name": principal.actor or "admin",
                "email": None,
            }
        elif principal.user_id:
            stored = db.get_user(principal.user_id)
            if stored is None:
                raise HTTPException(status_code=401, detail="user not found")
            actor = stored
        else:
            raise HTTPException(status_code=403, detail="only a track owner or admin can mint agents")
        return mint_agent_for_owner(
            db,
            owner=actor,
            display_name=body.display_name,
            metadata=_merge_signup_metadata(body),
            track=body.track,
        )

    def _agent_target(principal: Principal, user_id: str) -> dict[str, Any]:
        target = db.get_user(user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="user not found")
        if principal.kind == "admin" or principal.role == "admin":
            return target
        if principal.user_id == user_id:
            return target
        if principal.kind == "owner" and target.get("track") == principal.track:
            return target
        raise HTTPException(status_code=403, detail="cannot manage this user")

    @app.post("/api/agents/{user_id}/rotate_key")
    def rotate_agent_key(
        user_id: str,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        target = _agent_target(principal, user_id)
        if target["kind"] not in {"owner", "agent"}:
            raise HTTPException(status_code=403, detail="only owner/agent keys rotate here")
        return rotate_user_key(db, target)

    @app.post("/api/agents/{user_id}/disable")
    def disable_agent_endpoint(
        user_id: str,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        require_owner_or_admin(principal)
        target = _agent_target(principal, user_id)
        if target["kind"] == "admin":
            raise HTTPException(status_code=403, detail="cannot disable admin")
        return {"user": disable_agent(db, target)}

    @app.get("/api/meta")
    def meta(principal: Principal = Depends(principal_dep)) -> dict[str, Any]:
        return {
            "statuses": list(STATUSES),
            "roles": list(ROLES),
            "tracks": list(TRACKS),
            "capabilities": capabilities(principal.role),
            "owner": "maintainer",
            "heartbeat_s": 10,
            "queue_kinds": list(QUEUE_KINDS),
            "queue_lease_m": 15,
            "catalog_updated_at": pack.meta_without_ensure().catalog_updated_at,
            "catalog_max_age_days": 7,
            "a2a": {
                "agent_card": "/.well-known/agent-card.json",
                "jsonrpc": "/a2a",
                "protocolVersion": "0.3.0",
            },
            "candidate_onboarded": candidate_onboarded(settings),
        }

    @app.get("/api/whoami")
    def whoami(principal: Principal = Depends(principal_dep)) -> dict[str, Any]:
        return _principal_payload(principal)

    @app.get("/api/jobs")
    def list_jobs(
        principal: Principal = Depends(principal_dep),
        status_filter: Annotated[str | None, Query(alias="status")] = None,
        q: str | None = None,
        stopped: bool | None = None,
    ) -> dict[str, Any]:
        if status_filter:
            validate_status(status_filter)
        jobs = db.list_jobs(status=status_filter, q=q, stopped=stopped)
        claims = queue.claims_for_jobs([job["id"] for job in jobs])
        for job in jobs:
            job["claim"] = claims.get(job["id"])
        total = len(db.list_jobs())
        return {
            "jobs": jobs,
            "count": len(jobs),
            "total": total,
            "role": principal.role,
        }

    @app.get("/api/jobs/{job_id}")
    def get_job(
        job_id: str,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        job = db.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        claims = queue.claims_for_jobs([job_id])
        job["claim"] = claims.get(job_id)
        return {"job": job, "role": principal.role}

    @app.post("/api/jobs", status_code=201)
    def create_job(
        body: JobIn,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        raw = body.model_dump(exclude_none=True)
        payload = authorize_create(principal.role, {k: v for k, v in raw.items() if v != ""})
        job_id = _normalize_id(payload["id"]) if payload.get("id") else _slug_id(
            payload["company"], payload["title"]
        )
        if db.get_job(job_id):
            raise HTTPException(status_code=409, detail=f"job id already exists: {job_id}")
        dup = db.find_duplicate(
            apply_url=str(payload.get("apply_url") or ""),
            company=payload["company"],
            title=payload["title"],
            location=str(payload.get("location") or ""),
        )
        if dup:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "duplicate job",
                    "existing_id": dup["id"],
                    "matched": "apply_url or company+title+location",
                },
            )
        payload["id"] = job_id
        payload["created_by_role"] = principal.role
        stored = db.insert_job(payload)
        event = db.add_event(
            job_id=job_id,
            actor_role=principal.role,
            actor=principal.actor,
            action="create",
            from_status=None,
            to_status=stored["status"],
            note="created",
            fields={"company": stored["company"], "title": stored["title"]},
        )
        queue.sync_system_items(stored, actor_role=principal.role, actor=principal.actor)
        return {"job": stored, "event": event}

    @app.patch("/api/jobs/{job_id}")
    def patch_job(
        job_id: str,
        body: JobPatch,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        current = db.get_job(job_id)
        if current is None:
            raise HTTPException(status_code=404, detail="job not found")
        incoming = body.model_dump(exclude_none=True)
        if not incoming:
            return {"job": current, "event": None}
        patch = authorize_patch(principal.role, current, incoming)
        stored = db.update_job(job_id, patch)
        event = db.add_event(
            job_id=job_id,
            actor_role=principal.role,
            actor=principal.actor,
            action="patch",
            from_status=current["status"],
            to_status=stored["status"],
            note="patched " + ", ".join(sorted(patch)),
            fields=patch,
        )
        queue.sync_system_items(stored, actor_role=principal.role, actor=principal.actor)
        return {"job": stored, "event": event}

    @app.post("/api/jobs/{job_id}/stop")
    def stop_job(
        job_id: str,
        body: StopIn,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_stop(principal.role)
        current = db.get_job(job_id)
        if current is None:
            raise HTTPException(status_code=404, detail="job not found")
        stored = db.update_job(
            job_id,
            {
                "stopped": True,
                "stop_reason": body.reason,
                "status": "closed_withdrawn",
            },
        )
        event = db.add_event(
            job_id=job_id,
            actor_role=principal.role,
            actor=principal.actor,
            action="stop",
            from_status=current["status"],
            to_status=stored["status"],
            note=body.reason,
        )
        return {"job": stored, "event": event}

    @app.post("/api/jobs/{job_id}/pause")
    def pause_job(
        job_id: str,
        body: PauseIn,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_stop(principal.role)
        current = db.get_job(job_id)
        if current is None:
            raise HTTPException(status_code=404, detail="job not found")
        stored = db.update_job(
            job_id,
            {
                "stopped": True,
                "stop_reason": body.reason,
            },
        )
        event = db.add_event(
            job_id=job_id,
            actor_role=principal.role,
            actor=principal.actor,
            action="pause",
            from_status=current["status"],
            to_status=stored["status"],
            note=body.reason,
        )
        return {"job": stored, "event": event}

    @app.post("/api/jobs/{job_id}/resume")
    def resume_job(
        job_id: str,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_stop(principal.role)
        current = db.get_job(job_id)
        if current is None:
            raise HTTPException(status_code=404, detail="job not found")
        stored = db.update_job(
            job_id,
            {
                "stopped": False,
                "stop_reason": "",
            },
        )
        event = db.add_event(
            job_id=job_id,
            actor_role=principal.role,
            actor=principal.actor,
            action="resume",
            from_status=current["status"],
            to_status=stored["status"],
            note="resumed",
        )
        return {"job": stored, "event": event}

    @app.delete("/api/jobs/{job_id}")
    def delete_job(
        job_id: str,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_delete(principal.role)
        current = db.get_job(job_id)
        if current is None:
            raise HTTPException(status_code=404, detail="job not found")
        db.delete_job(job_id)
        event = db.add_event(
            job_id=job_id,
            actor_role=principal.role,
            actor=principal.actor,
            action="delete",
            from_status=current["status"],
            to_status=None,
            note="deleted",
        )
        return {"ok": True, "id": job_id, "event": event}

    @app.get("/api/events")
    def list_events(
        principal: Principal = Depends(principal_dep),
        job_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return {"events": db.list_events(job_id=job_id, limit=limit), "role": principal.role}

    @app.get("/api/hygiene")
    def hygiene_report(
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_hygiene(principal.role)
        jobs = db.list_jobs()
        by_url: dict[str, list[str]] = {}
        by_ctl: dict[tuple[str, str, str], list[str]] = {}
        stale: list[str] = []
        missing_packet: list[str] = []
        for job in jobs:
            url = (job.get("apply_url") or "").strip()
            if url:
                by_url.setdefault(url, []).append(job["id"])
            key = (
                (job.get("company") or "").lower(),
                (job.get("title") or "").lower(),
                (job.get("location") or "").lower(),
            )
            by_ctl.setdefault(key, []).append(job["id"])
            if job["status"] in {"applying", "outreaching"}:
                stale.append(job["id"])
            packet = job.get("apply_packet") or {}
            if job["status"] == "apply_ready" and not packet.get("url") and not packet.get("steps"):
                missing_packet.append(job["id"])
        return {
            "counts_by_status": db.counts_by_status(),
            "duplicate_apply_urls": [
                {"apply_url": url, "ids": ids} for url, ids in by_url.items() if len(ids) > 1
            ],
            "duplicate_company_title_location": [
                {"company": k[0], "title": k[1], "location": k[2], "ids": ids}
                for k, ids in by_ctl.items()
                if len(ids) > 1
            ],
            "active_claims": stale,
            "apply_ready_missing_packet": missing_packet,
            "stopped": [j["id"] for j in jobs if j.get("stopped")],
        }

    @app.post("/api/hygiene/vacuum")
    def hygiene_vacuum(
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_hygiene(principal.role)
        db.vacuum()
        db.add_event(
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="vacuum",
            note="sqlite vacuum",
        )
        return {"ok": True}

    @app.post("/api/import")
    def import_history(
        body: ImportIn,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_import(principal.role)
        if body.replace and principal.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="only admin can replace the board during import",
            )
        if body.replace:
            for job in db.list_jobs():
                db.delete_job(job["id"])
        created = 0
        updated = 0
        skipped = 0
        for raw in body.jobs:
            if not isinstance(raw, dict) or not raw.get("company") or not raw.get("title"):
                skipped += 1
                continue
            job_id = str(raw.get("id") or _slug_id(str(raw["company"]), str(raw["title"])))
            if not ID_RE.match(job_id):
                skipped += 1
                continue
            existing = db.get_job(job_id)
            row = {
                "id": job_id,
                "company": raw["company"],
                "title": raw["title"],
                "location": raw.get("location") or "",
                "remote": raw.get("remote"),
                "url": raw.get("url") or "",
                "apply_url": raw.get("apply_url") or "",
                "apply_kind": raw.get("apply_kind") or "",
                "ats": raw.get("ats") or "",
                "req_id": str(raw.get("req_id") or ""),
                "sources": raw.get("sources") or [],
                "status": raw.get("status") or "discovered",
                "score": raw.get("score"),
                "owners": raw.get("owners") or {},
                "apply_packet": raw.get("apply_packet") or {},
                "outreach_packet": raw.get("outreach_packet") or {},
                "research": raw.get("research") or {},
                "proof": raw.get("proof") or {},
                "notes": raw.get("notes") or "",
                "conflicts": raw.get("conflicts") or [],
                "stopped": bool(raw.get("stopped")),
                "stop_reason": raw.get("stop_reason") or "",
                "created_at": raw.get("created_at"),
                "updated_at": raw.get("updated_at"),
                "created_by_role": principal.role,
            }
            try:
                validate_status(str(row["status"]))
            except HTTPException:
                skipped += 1
                continue
            if existing:
                db.update_job(job_id, {k: v for k, v in row.items() if k != "id"})
                updated += 1
            else:
                db.insert_job(row)
                created += 1
        for raw_event in body.events:
            if not isinstance(raw_event, dict):
                continue
            db.add_event(
                job_id=raw_event.get("job_id"),
                actor_role=str(raw_event.get("role") or raw_event.get("actor_role") or principal.role),
                actor=str(raw_event.get("actor") or ""),
                action=str(raw_event.get("action") or "import"),
                from_status=raw_event.get("from"),
                to_status=raw_event.get("to"),
                note=str(raw_event.get("note") or "imported"),
            )
        db.add_event(
            job_id=None,
            actor_role=principal.role,
            actor=principal.actor,
            action="import",
            note=f"created={created} updated={updated} skipped={skipped}",
        )
        return {"created": created, "updated": updated, "skipped": skipped}

    @app.post("/api/metrics/token_burn", status_code=201)
    def log_token_burn(
        body: TokenBurnIn,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        payload = body.model_dump(exclude_none=True)
        extra = payload.pop("extra", None) or {}
        for key in list(payload.keys()):
            if key not in {
                "tool_name",
                "skill",
                "lane",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "cost_usd",
                "duration_ms",
                "job_id",
                "timestamp",
            }:
                extra[key] = payload.pop(key)
        payload["extra"] = extra
        payload["actor_role"] = principal.role
        payload["actor"] = principal.actor
        stored = metrics.record_token_burn(payload)
        return {"ok": True, "row": stored}

    @app.get("/api/metrics/token_burn")
    def list_token_burn(
        principal: Principal = Depends(principal_dep),
        limit: int = 100,
    ) -> dict[str, Any]:
        ensure_can_read_metrics(principal.role)
        return {"rows": metrics.list_burns(limit=limit)}

    @app.get("/api/metrics/summary")
    def metrics_summary(
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        ensure_can_read_metrics(principal.role)
        return metrics.summary()

    @app.exception_handler(HTTPException)
    async def http_exc(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    mount_presence(app, db, principal_dep)
    return app
