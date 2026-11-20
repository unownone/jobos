"""jobOS MCP: tools the connected agent uses to hunt, remember, and keep looping."""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import HTTPException, Request

from app.agent_flow import (
    LANES,
    LANE_NEEDS,
    AgentFlow,
    capability_preface,
    evaluate_lane,
    plan_loop,
    skill_lane,
)
from app.auth import Principal
from app.db import BoardDB
from app.mcp_store import McpStore
from app.memory_policy import MemoryError
from app.memory_store import grouped_recall, insert_item
from app.people import list_people
from app.permissions import authorize_create, authorize_patch
from app.profile import candidate_status
from app.skill_store import SkillStore
from app.tenant import TenantContext

PROTOCOL = "2025-03-26"
SUPPORTED = {PROTOCOL, "2025-06-18", "2024-11-05"}
ID_RE = re.compile(r"^[a-z0-9]+__[a-zA-Z0-9._-]+$")
SLUG_RE = re.compile(r"[^a-z0-9]+")

INSTRUCTIONS = (
    "You are connected to jobOS as one agent. You are not stuck in a single lane. "
    "The human observes, shares insights, and steers. You do the work. "
    "Call get_started. If lanes are empty, ask the human which of find, apply, and outreach "
    "this session should run — they may pick more than one — then set_session_lanes. "
    "Call report_capabilities with the truth: browser only if you can drive a browser here, "
    "email only if a mailbox is connected. "
    "Before find, apply, or outreach, call evaluate_lane. Find and apply need a browser. "
    "Outreach needs email. If can is false, stop and tell the human. "
    "Use start_loop and keep calling next_loop until the loop is done or blocked. "
    "Do not wait for the human to ask again. Read skills with read_skill. "
    "Record what you used with record_use. Read steers with read_steers. "
    "The older Hub HTTP API still exists for invite-key bots. Prefer these tools."
)


def tool_result(payload: Any, *, error: bool = False) -> dict[str, Any]:
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": error}


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        body["required"] = required
    return body


def tool_catalog() -> list[dict[str, Any]]:
    lane = {"type": "string", "enum": list(LANES)}
    return [
        {
            "name": "get_started",
            "description": (
                "First call after connect, and whenever the human says get started, find jobs, "
                "apply jobs, or outreach jobs. Returns session lanes, capability gaps, steers, and the prompts to follow."
            ),
            "inputSchema": _schema({}),
        },
        {
            "name": "ask_session_lanes",
            "description": (
                "Returns the question you must ask the human. Does not set lanes. "
                "You manage the session. jobOS does not pick lanes."
            ),
            "inputSchema": _schema({}),
        },
        {
            "name": "set_session_lanes",
            "description": (
                "Store the lanes the human just chose for this agent session. "
                "Call only after they answer. Pass the full set. One agent may hold several lanes."
            ),
            "inputSchema": _schema(
                {"lanes": {"type": "array", "items": lane, "minItems": 1}},
                ["lanes"],
            ),
        },
        {
            "name": "report_capabilities",
            "description": (
                "Report what this client can actually do. browser true only with a real browser. "
                "email true only with a connected mailbox. False is a valid answer."
            ),
            "inputSchema": _schema(
                {"browser": {"type": "boolean"}, "email": {"type": "boolean"}},
                ["browser", "email"],
            ),
        },
        {
            "name": "evaluate_lane",
            "description": (
                "Call before find, apply, or outreach. can false means stop and tell the human what is missing."
            ),
            "inputSchema": _schema({"lane": lane}, ["lane"]),
        },
        {
            "name": "list_skills",
            "description": "Skills for a lane, each with the capability it needs. Evaluate before you run one.",
            "inputSchema": _schema({"lane": lane}),
        },
        {
            "name": "read_skill",
            "description": "Full skill playbook, with the capability gate in front. Record the slug with record_use when you follow it.",
            "inputSchema": _schema({"slug": {"type": "string"}}, ["slug"]),
        },
        {
            "name": "list_mcps",
            "description": "External MCP catalog (browser, email, search). This connection is jobOS itself.",
            "inputSchema": _schema({"lane": lane}),
        },
        {
            "name": "recall_memory",
            "description": "Durable facts for this account. Do not treat a job description as memory.",
            "inputSchema": _schema({"q": {"type": "string"}, "limit": {"type": "integer"}}),
        },
        {
            "name": "write_memory",
            "description": (
                "Store one durable fact (portal quirk, blocker, dead tool). "
                "Title 8–120 characters. Body at least 40 characters. Not a JD and not a secret."
            ),
            "inputSchema": _schema(
                {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "kind": {"type": "string"},
                    "pod": {"type": "string"},
                },
                ["title", "body"],
            ),
        },
        {
            "name": "read_steers",
            "description": "Insights the human left for you. Follow them on the next loop step.",
            "inputSchema": _schema({}),
        },
        {
            "name": "record_use",
            "description": "Record a skill or external MCP you actually used this session.",
            "inputSchema": _schema(
                {
                    "kind": {"type": "string", "enum": ["skill", "mcp"]},
                    "slug": {"type": "string"},
                    "note": {"type": "string"},
                },
                ["kind", "slug"],
            ),
        },
        {
            "name": "list_jobs",
            "description": "Short job list for the live board. Use get_job before writing.",
            "inputSchema": _schema(
                {"status": {"type": "string"}, "limit": {"type": "integer"}},
            ),
        },
        {
            "name": "get_job",
            "description": "One job, including packets and proof.",
            "inputSchema": _schema({"job_id": {"type": "string"}}, ["job_id"]),
        },
        {
            "name": "create_job",
            "description": "Create a discovered job. Requires the find lane and a browser. Never Easy Apply from here.",
            "inputSchema": _schema(
                {
                    "company": {"type": "string"},
                    "title": {"type": "string"},
                    "id": {"type": "string"},
                    "location": {"type": "string"},
                    "url": {"type": "string"},
                    "apply_url": {"type": "string"},
                    "apply_kind": {"type": "string"},
                    "ats": {"type": "string"},
                    "status": {"type": "string"},
                    "score": {"type": "number"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "string"},
                    "description": {"type": "string"},
                    "pay": {"type": "string"},
                    "apply_packet": {"type": "object"},
                },
                ["company", "title"],
            ),
        },
        {
            "name": "update_job",
            "description": (
                "Patch a job on the lane you pass. evaluate_lane must pass for that lane. "
                "Use find while sourcing, apply when submitting, outreach when recording a touch."
            ),
            "inputSchema": _schema(
                {
                    "job_id": {"type": "string"},
                    "lane": lane,
                    "patch": {"type": "object"},
                },
                ["job_id", "lane", "patch"],
            ),
        },
        {
            "name": "list_people",
            "description": "People already on the board. Requires the outreach lane and email.",
            "inputSchema": _schema({"job_id": {"type": "string"}, "q": {"type": "string"}}),
        },
        {
            "name": "start_loop",
            "description": (
                "Start a loop so you keep working without another human message. "
                "Then call next_loop until status is done or blocked."
            ),
            "inputSchema": _schema(
                {"lane": lane, "goal": {"type": "string"}},
                ["lane"],
            ),
        },
        {
            "name": "next_loop",
            "description": "The next step of the running loop. Call it again after you finish that step.",
            "inputSchema": _schema({"loop_id": {"type": "string"}}),
        },
        {
            "name": "stop_loop",
            "description": "Stop a loop when the human says to stop or the work is done.",
            "inputSchema": _schema({"loop_id": {"type": "string"}, "reason": {"type": "string"}}),
        },
        {
            "name": "list_loops",
            "description": "Loops on this agent session.",
            "inputSchema": _schema({}),
        },
        {
            "name": "list_actions",
            "description": "Every tool on this MCP connection, plus a note that the older HTTP API still exists.",
            "inputSchema": _schema({}),
        },
    ]


def _slug_id(company: str, title: str) -> str:
    slug = SLUG_RE.sub("-", f"{company}-{title}".lower()).strip("-")[:72]
    return f"board__{slug or 'job'}"


def _principal(grant: dict[str, Any], session: dict[str, Any]) -> Principal:
    return Principal(
        role="admin",
        actor=session.get("label") or "mcp-agent",
        user_id=grant["user_id"],
        track=None,
        kind="admin",
        auth="mcp",
        account_id=grant["account_id"],
    )


def _summary(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job.get("id"),
        "company": job.get("company"),
        "title": job.get("title"),
        "status": job.get("status"),
        "score": job.get("score"),
        "location": job.get("location"),
        "apply_url": job.get("apply_url"),
        "apply_kind": job.get("apply_kind"),
        "sources": job.get("sources") or [],
        "stopped": bool(job.get("stopped")),
    }


class McpEngine:
    def __init__(self, request: Request, flow: AgentFlow, grant: dict[str, Any], session: dict[str, Any]) -> None:
        self.request = request
        self.flow = flow
        self.grant = grant
        self.session = session
        self.db: BoardDB = request.app.state.db
        self.settings = request.app.state.settings
        self.principal = _principal(grant, session)
        self.tenant: TenantContext = self.principal.tenant

    def call(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        args = arguments or {}
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            return tool_result({"error": f"unknown tool {name}"}, error=True)
        try:
            return tool_result(handler(args))
        except HTTPException as exc:
            detail = exc.detail
            return tool_result({"error": detail if isinstance(detail, str) else detail}, error=True)
        except (MemoryError, ValueError) as exc:
            return tool_result({"error": str(exc)}, error=True)

    def _reload(self) -> dict[str, Any]:
        session = self.flow.get_session(self.grant["account_id"], self.session["id"])
        if session is None:
            raise ValueError("session ended")
        self.session = session
        return session

    def _gate(self, lane: str) -> dict[str, Any]:
        result = evaluate_lane(self.session, lane)
        if not result["can"]:
            raise ValueError(result["instruction"])
        return result

    def _candidate_ready(self) -> dict[str, Any]:
        status = candidate_status(self.settings, self.db, tenant=self.tenant)
        if not status["onboarded"]:
            raise ValueError(
                "The candidate profile is not onboarded. Tell the human to finish /onboarding. Do not invent one."
            )
        return status

    def tool_get_started(self, _args: dict[str, Any]) -> dict[str, Any]:
        status = candidate_status(self.settings, self.db, tenant=self.tenant)
        lanes = list(self.session.get("lanes") or [])
        checks = {lane: evaluate_lane(self.session, lane) for lane in (lanes or LANES)}
        return {
            "prompts": ["get started", "find jobs", "apply jobs", "outreach jobs"],
            "session": self.session,
            "candidate": {
                "onboarded": status["onboarded"],
                "resume_present": status["resume_present"],
                "missing": status["missing"],
                "onboarding_url": "/onboarding",
            },
            "lane_checks": checks,
            "steers": self.flow.list_steers(self.grant["account_id"], session_id=self.session["id"], limit=5),
            "loops": self.flow.list_loops(self.grant["account_id"], self.session["id"]),
            "read_first": "agent-session",
            "instruction": (
                "If lanes are empty, ask the human which lanes this session should run, then set_session_lanes. "
                "If capabilities are not reported, call report_capabilities before any lane. "
                "If the human named a lane and evaluate_lane.can is true, start_loop and keep calling next_loop."
            ),
        }

    def tool_ask_session_lanes(self, _args: dict[str, Any]) -> dict[str, Any]:
        lanes = list(self.session.get("lanes") or [])
        question = (
            "Which lanes should I run in this session? I can do find, apply, and outreach. "
            "Pick any combination. I will keep that choice for this session."
        )
        if lanes:
            question = (
                f"This session is set to {', '.join(lanes)}. "
                "Should I keep that, or change the lanes?"
            )
        return {"ask_human": question, "allowed": list(LANES), "current": lanes}

    def tool_set_session_lanes(self, args: dict[str, Any]) -> dict[str, Any]:
        session = self.flow.set_lanes(self.grant["account_id"], self.session["id"], list(args.get("lanes") or []))
        self.session = session
        return {
            "session": session,
            "instruction": "Lanes are stored on this agent session. Report capabilities if you have not, then evaluate each lane before work.",
        }

    def tool_report_capabilities(self, args: dict[str, Any]) -> dict[str, Any]:
        session = self.flow.set_capabilities(
            self.grant["account_id"],
            self.session["id"],
            browser=bool(args.get("browser")),
            email=bool(args.get("email")),
        )
        self.session = session
        return {"session": session, "checks": {lane: evaluate_lane(session, lane) for lane in LANES}}

    def tool_evaluate_lane(self, args: dict[str, Any]) -> dict[str, Any]:
        return evaluate_lane(self.session, str(args.get("lane") or ""))

    def tool_list_skills(self, args: dict[str, Any]) -> dict[str, Any]:
        store = SkillStore(self.db, self.tenant)
        wanted = str(args.get("lane") or "").strip()
        rows = []
        for skill in store.list_visible(self.principal, status="approved", limit=200):
            lane = skill_lane(skill)
            if wanted and lane != wanted and skill.get("slug") != "agent-session":
                continue
            needs = list(LANE_NEEDS[lane]) if lane else []
            rows.append(
                {
                    "slug": skill["slug"],
                    "name": skill["name"],
                    "role": skill["role"],
                    "tags": skill["tags"],
                    "lane": lane,
                    "needs": needs,
                    "evaluate_before_use": bool(lane),
                }
            )
        return {"skills": rows, "instruction": "Call evaluate_lane before a skill whose lane is set. Then read_skill."}

    def tool_read_skill(self, args: dict[str, Any]) -> dict[str, Any]:
        slug = str(args.get("slug") or "").strip()
        store = SkillStore(self.db, self.tenant)
        found = store.get_shared_by_slug(slug)
        if found is None or found.get("status") != "approved":
            raise ValueError(f"no approved skill {slug}")
        lane = skill_lane(found)
        body = capability_preface(lane) + "\n" + (found.get("body") or "")
        return {
            "slug": found["slug"],
            "name": found["name"],
            "lane": lane,
            "needs": list(LANE_NEEDS[lane]) if lane else [],
            "body": body,
        }

    def tool_list_mcps(self, args: dict[str, Any]) -> dict[str, Any]:
        store = McpStore(self.db, self.tenant)
        wanted = str(args.get("lane") or "").strip()
        rows = []
        for item in store.list_visible(limit=200):
            roles = {str(role).lower() for role in item.get("roles") or []}
            if wanted == "find" and roles and "discovery" not in roles and "research" not in roles:
                continue
            if wanted == "apply" and roles and "apply" not in roles:
                continue
            if wanted == "outreach" and roles and "outreach" not in roles:
                continue
            rows.append(
                {
                    "slug": item["slug"],
                    "name": item["name"],
                    "status": item["status"],
                    "auth": item.get("auth") or "",
                    "install": item.get("install") or "",
                    "notes": item.get("notes") or "",
                    "roles": item.get("roles") or [],
                }
            )
        return {
            "mcps": rows,
            "note": "A browser MCP is required before find or apply. An email connection is required before outreach.",
        }

    def tool_recall_memory(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = int(args.get("limit") or 12)
        payload = grouped_recall(
            self.db,
            self.principal,
            q=(str(args.get("q")).strip() if args.get("q") else None),
            limit=limit,
            compact=True,
        )
        return payload

    def tool_write_memory(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = str(args.get("kind") or "process_note")
        pod = str(args.get("pod") or "common")
        item = insert_item(
            self.db,
            self.principal,
            pod=pod,
            kind=kind,
            title=str(args.get("title") or ""),
            body=str(args.get("body") or ""),
        )
        return {"item": {"id": item["id"], "pod": item["pod"], "kind": item["kind"], "title": item["title"]}}

    def tool_read_steers(self, _args: dict[str, Any]) -> dict[str, Any]:
        return {"steers": self.flow.list_steers(self.grant["account_id"], session_id=self.session["id"])}

    def tool_record_use(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.flow.record_use(
            self.grant["account_id"],
            self.session["id"],
            kind=str(args.get("kind") or ""),
            slug=str(args.get("slug") or ""),
            note=str(args.get("note") or ""),
        )

    def tool_list_jobs(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = max(1, min(int(args.get("limit") or 20), 50))
        status = str(args.get("status") or "").strip() or None
        jobs = self.db.list_jobs(self.tenant, status=status, limit=limit)
        return {"jobs": [_summary(job) for job in jobs], "count": len(jobs)}

    def tool_get_job(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = str(args.get("job_id") or "").strip()
        job = self.db.get_job(self.tenant, job_id)
        if job is None:
            raise ValueError("job not found")
        return {"job": job}

    def tool_create_job(self, args: dict[str, Any]) -> dict[str, Any]:
        self._candidate_ready()
        self._gate("find")
        payload = {key: value for key, value in args.items() if value not in (None, "")}
        payload = authorize_create("admin", payload)
        if payload.get("id"):
            job_id = str(payload["id"]).strip()
            if not ID_RE.match(job_id):
                raise ValueError("id must match {source}__{stable_id}")
        else:
            job_id = _slug_id(payload["company"], payload["title"])
        if self.db.get_job(self.tenant, job_id):
            raise ValueError(f"job id already exists: {job_id}")
        dup = self.db.find_duplicate(
            self.tenant,
            apply_url=str(payload.get("apply_url") or ""),
            company=payload["company"],
            title=payload["title"],
            location=str(payload.get("location") or ""),
        )
        if dup:
            raise ValueError(f"duplicate job: {dup['id']}")
        payload["id"] = job_id
        payload["created_by_role"] = "admin"
        stored = self.db.insert_job(self.tenant, payload)
        self.db.add_event(
            self.tenant,
            job_id=job_id,
            actor_role="admin",
            actor=self.principal.actor,
            action="create",
            from_status=None,
            to_status=stored["status"],
            note="created via mcp",
            fields={"company": stored["company"], "title": stored["title"]},
        )
        queue = getattr(self.request.app.state, "queue", None)
        if queue is not None:
            queue.sync_system_items(self.tenant, stored, actor_role="admin", actor=self.principal.actor)
        return {"job": _summary(stored), "instruction": "Do not apply from find. Call next_loop when this source is done."}

    def tool_update_job(self, args: dict[str, Any]) -> dict[str, Any]:
        self._candidate_ready()
        lane = str(args.get("lane") or "")
        self._gate(lane)
        job_id = str(args.get("job_id") or "").strip()
        current = self.db.get_job(self.tenant, job_id)
        if current is None:
            raise ValueError("job not found")
        incoming = args.get("patch")
        if not isinstance(incoming, dict) or not incoming:
            raise ValueError("patch object is required")
        patch = authorize_patch("admin", current, incoming)
        stored = self.db.update_job(self.tenant, job_id, patch)
        self.db.add_event(
            self.tenant,
            job_id=job_id,
            actor_role="admin",
            actor=self.principal.actor,
            action="patch",
            from_status=current["status"],
            to_status=stored["status"],
            note="patched via mcp " + ", ".join(sorted(patch)),
            fields=patch,
        )
        queue = getattr(self.request.app.state, "queue", None)
        if queue is not None:
            queue.sync_system_items(self.tenant, stored, actor_role="admin", actor=self.principal.actor)
        return {"job": _summary(stored)}

    def tool_list_people(self, args: dict[str, Any]) -> dict[str, Any]:
        self._gate("outreach")
        people = list_people(
            self.db,
            self.tenant,
            job_id=str(args.get("job_id") or "").strip() or None,
            q=str(args.get("q") or "").strip() or None,
        )
        slim = [
            {
                "id": person.get("id"),
                "name": person.get("name"),
                "title": person.get("title"),
                "company": person.get("company"),
                "job_id": person.get("job_id"),
                "email": person.get("email"),
                "do_not_contact": person.get("do_not_contact"),
            }
            for person in people[:30]
        ]
        return {"people": slim}

    def tool_start_loop(self, args: dict[str, Any]) -> dict[str, Any]:
        lane = str(args.get("lane") or "")
        gate = self._gate(lane)
        if gate["lane"] in {"find", "apply"}:
            self._candidate_ready()
        loop = self.flow.start_loop(
            self.grant["account_id"],
            self.session["id"],
            lane=gate["lane"],
            goal=str(args.get("goal") or ""),
        )
        jobs = self.db.list_jobs(self.tenant, limit=200)
        step = plan_loop(loop, jobs)
        step["loop_id"] = loop["id"]
        step["steers"] = self.flow.list_steers(self.grant["account_id"], session_id=self.session["id"], limit=3)
        step["keep_going"] = "Call next_loop after this step. Do not wait for the human to ask again."
        return step

    def tool_next_loop(self, args: dict[str, Any]) -> dict[str, Any]:
        loop_id = str(args.get("loop_id") or "").strip() or None
        loop = self.flow.active_loop(self.grant["account_id"], self.session["id"], loop_id)
        if loop is None:
            raise ValueError("no running loop. start_loop after evaluate_lane passes.")
        if loop["status"] != "running":
            return {"loop_id": loop["id"], "status": loop["status"], "continue": False, "instruction": "This loop is not running."}
        try:
            self._gate(loop["lane"])
        except ValueError as exc:
            saved = self.flow.save_loop(
                self.grant["account_id"], loop["id"], status="blocked", step=int(loop["step"]) + 1
            )
            return {
                "loop_id": saved["id"],
                "status": "blocked",
                "continue": False,
                "instruction": str(exc),
            }
        jobs = self.db.list_jobs(self.tenant, limit=200)
        step = plan_loop(loop, jobs)
        saved = self.flow.save_loop(
            self.grant["account_id"],
            loop["id"],
            status=str(step["status"]),
            step=int(loop["step"]) + 1,
        )
        step["loop_id"] = saved["id"]
        step["step"] = saved["step"]
        step["steers"] = self.flow.list_steers(self.grant["account_id"], session_id=self.session["id"], limit=3)
        if step.get("continue"):
            step["keep_going"] = "Do this step, then call next_loop again."
        return step

    def tool_stop_loop(self, args: dict[str, Any]) -> dict[str, Any]:
        loop_id = str(args.get("loop_id") or "").strip()
        loop = self.flow.get_loop(self.grant["account_id"], loop_id)
        if loop is None or loop["session_id"] != self.session["id"]:
            raise ValueError("loop not found")
        saved = self.flow.save_loop(
            self.grant["account_id"], loop_id, status="stopped", step=int(loop["step"])
        )
        return {"loop": saved, "reason": str(args.get("reason") or "")}

    def tool_list_loops(self, _args: dict[str, Any]) -> dict[str, Any]:
        return {"loops": self.flow.list_loops(self.grant["account_id"], self.session["id"])}

    def tool_list_actions(self, _args: dict[str, Any]) -> dict[str, Any]:
        return {
            "tools": [tool["name"] for tool in tool_catalog()],
            "legacy_api": (
                "Invite-key bots can still use /api/jobs and /api/queue with a Hub key. "
                "This MCP connection does not mint that key. Use these tools."
            ),
        }


def handle_rpc(engine: McpEngine, message: dict[str, Any]) -> dict[str, Any] | None:
    method = str(message.get("method") or "")
    msg_id = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if method.startswith("notifications/") or msg_id is None and method != "initialize":
        if method in {"notifications/initialized", "notifications/cancelled"}:
            return None
        if msg_id is None:
            return None
    if method == "initialize":
        client = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else {}
        name = str(client.get("name") or "").strip()
        if name:
            engine.flow.db.conn.execute(
                "UPDATE agent_sessions SET label = ? WHERE id = ? AND account_id = ?",
                (name[:120], engine.session["id"], engine.grant["account_id"]),
            )
            engine.flow.db.conn.commit()
            engine.session["label"] = name[:120]
        requested = str(params.get("protocolVersion") or PROTOCOL)
        version = requested if requested in SUPPORTED else PROTOCOL
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "jobos", "version": "1.0.0"},
                "instructions": INSTRUCTIONS,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tool_catalog()}}
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        return {"jsonrpc": "2.0", "id": msg_id, "result": engine.call(name, arguments)}
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }
