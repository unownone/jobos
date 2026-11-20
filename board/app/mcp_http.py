"""MCP streamable HTTP, OAuth for that connection, and the admin observe/steer API.

`/mcp` asks for OAuth. After approval the access token is short and the refresh
token keeps the same agent session alive. The older Hub API is untouched.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.agent_flow import SCOPE, AgentFlow, redirect_uri_allowed
from app.auth import Principal, authenticate, require_admin
from app.mcp_protocol import INSTRUCTIONS, McpEngine, handle_rpc
from app.profile import candidate_status

STATIC_DIR_NAME = "static"


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client_name: str | None = None
    redirect_uris: list[str] = Field(default_factory=list)
    grant_types: list[str] | None = None
    response_types: list[str] | None = None
    token_endpoint_auth_method: str | None = "none"
    scope: str | None = None


class AuthorizeIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client_id: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str = "S256"
    state: str
    scope: str | None = SCOPE
    resource: str | None = None
    decision: str


class SteerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str
    session_id: str | None = None


def external_origin(request: Request) -> str:
    settings = request.app.state.settings
    forwarded_host = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    if forwarded_host:
        proto = forwarded_proto or "https"
        return f"{proto}://{forwarded_host}".rstrip("/")
    configured = (getattr(settings, "public_url", "") or "").strip().rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


def _flow(request: Request) -> AgentFlow:
    return AgentFlow(request.app.state.db)


def _www_authenticate(origin: str) -> str:
    metadata = f"{origin}/.well-known/oauth-protected-resource/mcp"
    return f'Bearer realm="jobos", resource_metadata="{metadata}", scope="{SCOPE}"'


def _oauth_error(status_code: int, error: str, description: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "error_description": description},
        headers={"Cache-Control": "no-store"},
    )


def _with_query(uri: str, params: dict[str, str]) -> str:
    """Add the OAuth response without dropping query parameters the client registered."""
    parts = urlparse(uri)
    merged: dict[str, str] = {}
    for key, values in parse_qs(parts.query, keep_blank_values=True).items():
        merged[key] = values[-1] if values else ""
    merged.update(params)
    return urlunparse(parts._replace(query=urlencode(merged)))


def _session_user(request: Request) -> Principal | None:
    settings = request.app.state.settings
    db = request.app.state.db
    if not request.cookies.get("hub_session"):
        return None
    try:
        return authenticate(
            settings,
            db,
            request=request,
            hub_session=request.cookies.get("hub_session"),
            hub_csrf=request.cookies.get("hub_csrf"),
        )
    except HTTPException:
        return None


def _metadata(origin: str) -> dict[str, Any]:
    return {
        "issuer": origin,
        "authorization_endpoint": f"{origin}/oauth/authorize",
        "token_endpoint": f"{origin}/oauth/token",
        "registration_endpoint": f"{origin}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "scopes_supported": [SCOPE],
    }


def _protected(origin: str) -> dict[str, Any]:
    return {
        "resource": f"{origin}/mcp",
        "authorization_servers": [origin],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [SCOPE],
        "resource_documentation": f"{origin}/connect",
    }


def _consent_page(request: Request, principal: Principal, client: dict[str, Any]) -> HTMLResponse:
    query = request.query_params
    csrf = escape(request.cookies.get("hub_csrf") or "")
    fields = {
        "client_id": query.get("client_id") or "",
        "redirect_uri": query.get("redirect_uri") or "",
        "code_challenge": query.get("code_challenge") or "",
        "code_challenge_method": query.get("code_challenge_method") or "S256",
        "state": query.get("state") or "",
        "scope": query.get("scope") or SCOPE,
        "resource": query.get("resource") or "",
    }
    hidden = "".join(
        f'<input type="hidden" name="{escape(key)}" value="{escape(value)}" />' for key, value in fields.items()
    )
    name = escape(client["client_name"])
    who = escape(principal.actor or "admin")
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>Connect your AI — jobOS</title>
  <link rel="icon" href="/brand/favicon.png" type="image/png" />
  <link rel="stylesheet" href="/static/theme.css" />
  <link rel="stylesheet" href="/static/public.css" />
  <link rel="stylesheet" href="/static/hub.css" />
</head>
<body class="site">
  <main class="wrap doc" id="main">
    <h1>Connect {name}</h1>
    <p>Signed in as {who}. This is the only admin. Approving lets this AI read skills, memory, and jobs, and run find, apply, and outreach when you pick those lanes.</p>
    <ul>
      <li>The AI will ask which lanes this session should run.</li>
      <li>Find and apply need a browser. Outreach needs email.</li>
      <li>The connection stays up with a refresh token. You can revoke it on Agents.</li>
    </ul>
    <form id="consent">
      {hidden}
      <p>
        <button type="submit" name="decision" value="approve">Approve</button>
        <button type="submit" class="secondary" name="decision" value="deny">Deny</button>
      </p>
      <p class="muted" id="consentErr" role="alert"></p>
    </form>
  </main>
  <script>
    const csrf = "{csrf}";
    document.getElementById("consent").addEventListener("submit", async (ev) => {{
      ev.preventDefault();
      const form = ev.target;
      const decision = ev.submitter ? ev.submitter.value : "deny";
      const body = Object.fromEntries(new FormData(form).entries());
      body.decision = decision;
      const res = await fetch("/oauth/authorize", {{
        method: "POST",
        credentials: "same-origin",
        headers: {{ "Content-Type": "application/json", "X-CSRF": csrf }},
        body: JSON.stringify(body),
      }});
      const payload = await res.json().catch(() => ({{}}));
      if (!res.ok || !payload.redirect) {{
        document.getElementById("consentErr").textContent = (payload.error_description || payload.detail || "Could not approve");
        return;
      }}
      location.href = payload.redirect;
    }});
  </script>
</body>
</html>"""
    return HTMLResponse(body)


def _read_token_form(request: Request, raw: bytes) -> dict[str, str]:
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): "" if value is None else str(value) for key, value in payload.items()}
    text = raw.decode("utf-8", errors="replace")
    parsed = parse_qs(text, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def create_mcp_router(principal_dep: Any) -> APIRouter:
    router = APIRouter(tags=["agent-mcp"])

    @router.get("/.well-known/oauth-authorization-server")
    def authorization_server(request: Request) -> dict[str, Any]:
        return _metadata(external_origin(request))

    @router.get("/.well-known/oauth-protected-resource")
    @router.get("/.well-known/oauth-protected-resource/mcp")
    def protected_resource(request: Request) -> dict[str, Any]:
        return _protected(external_origin(request))

    @router.post("/oauth/register", status_code=201)
    def register(body: RegisterIn, request: Request) -> JSONResponse:
        method = (body.token_endpoint_auth_method or "none").strip()
        try:
            client = _flow(request).register_client(
                client_name=body.client_name or "AI client",
                redirect_uris=body.redirect_uris,
                auth_method=method,
            )
        except ValueError as exc:
            return _oauth_error(400, "invalid_client_metadata", str(exc))
        return JSONResponse(status_code=201, content=client)

    @router.get("/oauth/authorize", response_model=None)
    def authorize_get(request: Request) -> Response:
        principal = _session_user(request)
        if principal is None:
            nxt = request.url.path
            if request.url.query:
                nxt = f"{nxt}?{request.url.query}"
            return RedirectResponse(url=f"/login?next={quote(nxt, safe='/')}", status_code=302)
        if principal.kind != "admin":
            return HTMLResponse("<p>Only the admin can connect an agent.</p>", status_code=403)
        flow = _flow(request)
        client = flow.get_client(request.query_params.get("client_id") or "")
        redirect_uri = request.query_params.get("redirect_uri") or ""
        challenge = request.query_params.get("code_challenge") or ""
        method = (request.query_params.get("code_challenge_method") or "").upper()
        state = request.query_params.get("state") or ""
        if client is None or redirect_uri not in client["redirect_uris"]:
            return HTMLResponse("<p>Unknown client or redirect URI.</p>", status_code=400)
        if method != "S256" or not challenge or not state:
            return HTMLResponse("<p>PKCE S256, a code challenge, and state are required.</p>", status_code=400)
        resource = request.query_params.get("resource") or ""
        if resource and resource.rstrip("/") != f"{external_origin(request)}/mcp":
            return HTMLResponse("<p>This authorization is only for /mcp.</p>", status_code=400)
        return _consent_page(request, principal, client)

    @router.post("/oauth/authorize")
    def authorize_post(
        body: AuthorizeIn,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> JSONResponse:
        require_admin(principal)
        flow = _flow(request)
        client = flow.get_client(body.client_id)
        if client is None or body.redirect_uri not in client["redirect_uris"]:
            return _oauth_error(400, "invalid_request", "unknown client or redirect_uri")
        if not redirect_uri_allowed(body.redirect_uri):
            return _oauth_error(400, "invalid_request", "redirect_uri is not allowed")
        if body.code_challenge_method.upper() != "S256" or not body.code_challenge or not body.state:
            return _oauth_error(400, "invalid_request", "PKCE S256 and state are required")
        if body.decision == "deny":
            target = _with_query(
                body.redirect_uri,
                {"error": "access_denied", "state": body.state},
            )
            return JSONResponse({"redirect": target})
        if body.decision != "approve":
            return _oauth_error(400, "invalid_request", "decision must be approve or deny")
        if principal.user_id is None:
            return _oauth_error(403, "access_denied", "admin session required")
        code = flow.issue_code(
            client_id=body.client_id,
            account_id=principal.account_id or "",
            user_id=principal.user_id,
            redirect_uri=body.redirect_uri,
            code_challenge=body.code_challenge,
            scope=SCOPE,
        )
        target = _with_query(body.redirect_uri, {"code": code, "state": body.state})
        return JSONResponse({"redirect": target})

    @router.post("/oauth/token")
    async def token(request: Request) -> JSONResponse:
        form = _read_token_form(request, await request.body())
        grant_type = (form.get("grant_type") or "").strip()
        client_id = (form.get("client_id") or "").strip()
        client_secret = form.get("client_secret") or ""
        flow = _flow(request)
        client = flow.get_client(client_id)
        if client is None or not flow.client_secret_ok(client, client_secret or None):
            return _oauth_error(401, "invalid_client", "unknown client")
        try:
            if grant_type == "authorization_code":
                issued = flow.exchange_code(
                    code=form.get("code") or "",
                    client_id=client_id,
                    redirect_uri=form.get("redirect_uri") or "",
                    code_verifier=form.get("code_verifier") or "",
                )
            elif grant_type == "refresh_token":
                issued = flow.refresh(refresh_token=form.get("refresh_token") or "", client_id=client_id)
            else:
                return _oauth_error(400, "unsupported_grant_type", "use authorization_code or refresh_token")
        except ValueError:
            return _oauth_error(400, "invalid_grant", "code or refresh token was rejected")
        issued.pop("grant_id", None)
        return JSONResponse(issued, headers={"Cache-Control": "no-store"})

    @router.post("/mcp")
    async def mcp_post(request: Request) -> Response:
        origin = external_origin(request)
        auth = request.headers.get("authorization") or ""
        token = auth.split(" ", 1)[1].strip() if auth.lower().startswith("bearer ") else ""
        flow = _flow(request)
        grant, reason = flow.grant_for_access(token)
        if grant is None:
            return JSONResponse(
                status_code=401,
                content={"error": reason or "invalid_token"},
                headers={"WWW-Authenticate": _www_authenticate(origin), "Cache-Control": "no-store"},
            )
        header_session = (request.headers.get("mcp-session-id") or "").strip()
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "error": {"code": -32700, "message": "parse error"}})
        messages = payload if isinstance(payload, list) else [payload]
        initializing = any(isinstance(item, dict) and item.get("method") == "initialize" for item in messages)
        if header_session and grant.get("session_id") and header_session != grant.get("session_id") and not initializing:
            return JSONResponse(status_code=404, content={"error": "session not found"})
        session = flow.ensure_session(grant)
        if header_session and header_session != session["id"] and not initializing:
            return JSONResponse(status_code=404, content={"error": "session not found"})
        engine = McpEngine(request, flow, grant, session)
        replies: list[dict[str, Any]] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            reply = handle_rpc(engine, item)
            if reply is not None:
                replies.append(reply)
        headers = {"Mcp-Session-Id": session["id"], "Cache-Control": "no-store"}
        if not replies:
            return Response(status_code=202, headers=headers)
        body: Any = replies if isinstance(payload, list) else replies[0]
        return JSONResponse(body, headers=headers)

    @router.get("/mcp")
    def mcp_get() -> JSONResponse:
        return JSONResponse(
            status_code=405,
            content={"error": "use POST for MCP"},
            headers={"Allow": "POST, DELETE"},
        )

    @router.delete("/mcp")
    def mcp_delete(request: Request) -> Response:
        origin = external_origin(request)
        auth = request.headers.get("authorization") or ""
        token = auth.split(" ", 1)[1].strip() if auth.lower().startswith("bearer ") else ""
        flow = _flow(request)
        grant, reason = flow.grant_for_access(token)
        if grant is None:
            return JSONResponse(
                status_code=401,
                content={"error": reason or "invalid_token"},
                headers={"WWW-Authenticate": _www_authenticate(origin)},
            )
        session_id = (request.headers.get("mcp-session-id") or grant.get("session_id") or "").strip()
        if session_id:
            flow.end_session(grant["account_id"], session_id)
        return Response(status_code=204)

    @router.get("/connect", response_model=None)
    def connect_page(principal: Principal = Depends(principal_dep)) -> FileResponse:
        require_admin(principal)
        static = request_static()
        return FileResponse(static / "connect.html")

    @router.get("/api/agent/status")
    def agent_status(
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        require_admin(principal)
        origin = external_origin(request)
        flow = _flow(request)
        account_id = principal.account_id or ""
        status = candidate_status(request.app.state.settings, request.app.state.db, tenant=principal.tenant)
        grants = flow.list_grants(account_id)
        return {
            "mcp_url": f"{origin}/mcp",
            "instructions": INSTRUCTIONS,
            "prompts": ["get started", "find jobs", "apply jobs", "outreach jobs"],
            "candidate_onboarded": status["onboarded"],
            "grants": grants,
            "connected": bool(grants),
            "uses": flow.list_uses(account_id, limit=20),
            "steers": flow.list_steers(account_id, limit=20),
            "loops": [
                loop
                for grant in grants
                if grant.get("session")
                for loop in flow.list_loops(account_id, grant["session"]["id"])
            ],
        }

    @router.post("/api/agent/steers")
    def add_steer(
        body: SteerIn,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        require_admin(principal)
        if principal.user_id is None:
            raise HTTPException(status_code=403, detail="admin required")
        try:
            steer = _flow(request).add_steer(
                principal.account_id or "",
                author_user_id=principal.user_id,
                body=body.body,
                session_id=body.session_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"steer": steer}

    @router.post("/api/agent/grants/{grant_id}/revoke")
    def revoke_grant(
        grant_id: str,
        request: Request,
        principal: Principal = Depends(principal_dep),
    ) -> dict[str, Any]:
        require_admin(principal)
        ok = _flow(request).revoke_grant(principal.account_id or "", grant_id)
        if not ok:
            raise HTTPException(status_code=404, detail="grant not found")
        return {"ok": True, "id": grant_id}

    return router


def request_static() -> Path:
    return Path(__file__).resolve().parent / STATIC_DIR_NAME
