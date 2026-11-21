package httpapi

import (
	"encoding/json"
	"net/http"
	"net/url"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/unownone/jobos/server/internal/agentflow"
	"github.com/unownone/jobos/server/internal/store"
)

const agentInstructions = "You are connected to jobOS as one agent. You are not stuck in a single lane. " +
	"The human observes, shares insights, and steers. You do the work. " +
	"Call get_started. If lanes are empty, ask the human which of find, apply, and outreach " +
	"this session should run — they may pick more than one — then set_session_lanes. " +
	"Call report_capabilities with the truth: browser only if you can drive a browser here, " +
	"email only if a mailbox is connected. " +
	"Before find, apply, or outreach, call evaluate_lane. Find and apply need a browser. " +
	"Outreach needs email. If can is false, stop and tell the human. " +
	"Use start_loop and keep calling next_loop until the loop is done or blocked. " +
	"Do not wait for the human to ask again. Read skills with read_skill. " +
	"Record what you used with record_use. Read steers with read_steers. " +
	"The older Hub HTTP API still exists for invite-key bots. Prefer these tools."

func (s *Server) flow() *agentflow.Flow {
	if s.Flow == nil {
		s.Flow = agentflow.New()
	}
	return s.Flow
}

func (s *Server) mountAgent(r *gin.Engine) {
	r.GET("/.well-known/oauth-authorization-server", s.oauthMetadata)
	r.GET("/.well-known/oauth-protected-resource", s.oauthProtected)
	r.GET("/.well-known/oauth-protected-resource/mcp", s.oauthProtected)
	r.POST("/oauth/register", s.oauthRegister)
	r.GET("/oauth/authorize", s.oauthAuthorizeGet)
	r.POST("/oauth/token", s.oauthToken)
	r.POST("/mcp", s.mcpPost)
	r.GET("/mcp", s.mcpGet)
	r.DELETE("/mcp", s.mcpDelete)

	admin := r.Group("/")
	admin.Use(s.requireAuth)
	admin.POST("/oauth/authorize", s.oauthAuthorizePost)
	admin.GET("/connect", s.connectPage)
	admin.GET("/api/agent/status", s.agentStatus)
	admin.POST("/api/agent/steers", s.agentSteer)
	admin.POST("/api/agent/grants/:id/revoke", s.agentRevoke)
}

func (s *Server) oauthMetadata(c *gin.Context) {
	origin := strings.TrimRight(s.publicURL(c), "/")
	c.JSON(http.StatusOK, gin.H{
		"issuer": origin, "authorization_endpoint": origin + "/oauth/authorize",
		"token_endpoint": origin + "/oauth/token", "registration_endpoint": origin + "/oauth/register",
		"response_types_supported": []string{"code"}, "grant_types_supported": []string{"authorization_code", "refresh_token"},
		"code_challenge_methods_supported": []string{"S256"},
		"token_endpoint_auth_methods_supported": []string{"none", "client_secret_post"},
		"scopes_supported": []string{"jobos"},
	})
}

func (s *Server) oauthProtected(c *gin.Context) {
	origin := strings.TrimRight(s.publicURL(c), "/")
	c.JSON(http.StatusOK, gin.H{
		"resource": origin + "/mcp", "authorization_servers": []string{origin},
		"bearer_methods_supported": []string{"header"}, "scopes_supported": []string{"jobos"},
		"resource_documentation": origin + "/connect",
	})
}

func (s *Server) oauthRegister(c *gin.Context) {
	var body struct {
		ClientName string   `json:"client_name"`
		Redirects  []string `json:"redirect_uris"`
		Method     string   `json:"token_endpoint_auth_method"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	out, err := s.flow().RegisterClient(body.ClientName, body.Method, body.Redirects)
	if err != nil {
		oauthFail(c, 400, "invalid_client_metadata", err.Error())
		return
	}
	c.JSON(http.StatusCreated, out)
}

func (s *Server) oauthAuthorizeGet(c *gin.Context) {
	p, err := s.authenticate(c)
	if err != nil {
		next := c.Request.URL.RequestURI()
		c.Redirect(http.StatusFound, "/login?next="+url.QueryEscape(next))
		return
	}
	if p.Role != "admin" {
		c.Data(http.StatusForbidden, "text/html; charset=utf-8", []byte("<p>Only the admin can connect an agent.</p>"))
		return
	}
	client, ok := s.flow().Client(c.Query("client_id"))
	redirectURI := c.Query("redirect_uri")
	if !ok || !containsStr(client.Redirects, redirectURI) {
		c.Data(http.StatusBadRequest, "text/html; charset=utf-8", []byte("<p>Unknown client or redirect URI.</p>"))
		return
	}
	if !strings.EqualFold(c.Query("code_challenge_method"), "S256") || c.Query("code_challenge") == "" || c.Query("state") == "" {
		c.Data(http.StatusBadRequest, "text/html; charset=utf-8", []byte("<p>PKCE S256, a code challenge, and state are required.</p>"))
		return
	}
	resource := strings.TrimRight(c.Query("resource"), "/")
	if resource != "" && resource != strings.TrimRight(s.publicURL(c), "/")+"/mcp" {
		c.Data(http.StatusBadRequest, "text/html; charset=utf-8", []byte("<p>This authorization is only for /mcp.</p>"))
		return
	}
	csrf, _ := c.Cookie(cookieCSRF)
	page := "<!doctype html><title>Connect agent</title><h1>Connect " + htmlEscape(client.Name) + "</h1>" +
		"<form method=\"post\" action=\"/oauth/authorize\">" +
		"<input type=\"hidden\" name=\"_csrf\" value=\"" + htmlEscape(csrf) + "\">" +
		"<input type=\"hidden\" name=\"client_id\" value=\"" + htmlEscape(c.Query("client_id")) + "\">" +
		"<input type=\"hidden\" name=\"redirect_uri\" value=\"" + htmlEscape(redirectURI) + "\">" +
		"<input type=\"hidden\" name=\"code_challenge\" value=\"" + htmlEscape(c.Query("code_challenge")) + "\">" +
		"<input type=\"hidden\" name=\"code_challenge_method\" value=\"S256\">" +
		"<input type=\"hidden\" name=\"state\" value=\"" + htmlEscape(c.Query("state")) + "\">" +
		"<button name=\"decision\" value=\"approve\">Approve</button>" +
		"<button name=\"decision\" value=\"deny\">Deny</button></form>"
	c.Data(http.StatusOK, "text/html; charset=utf-8", []byte(page))
}

func (s *Server) oauthAuthorizePost(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" {
		oauthFail(c, 403, "access_denied", "admin session required")
		return
	}
	body := map[string]string{}
	if strings.Contains(c.GetHeader("Content-Type"), "application/json") {
		var raw map[string]string
		if err := c.BindJSON(&raw); err != nil {
			return
		}
		body = raw
	} else {
		_ = c.Request.ParseForm()
		for key, values := range c.Request.PostForm {
			if len(values) > 0 {
				body[key] = values[0]
			}
		}
	}
	client, ok := s.flow().Client(body["client_id"])
	if !ok || !containsStr(client.Redirects, body["redirect_uri"]) || !agentflow.RedirectURIAllowed(body["redirect_uri"]) {
		oauthFail(c, 400, "invalid_request", "unknown client or redirect_uri")
		return
	}
	if !strings.EqualFold(body["code_challenge_method"], "S256") || body["code_challenge"] == "" || body["state"] == "" {
		oauthFail(c, 400, "invalid_request", "PKCE S256 and state are required")
		return
	}
	if body["decision"] == "deny" {
		c.JSON(http.StatusOK, gin.H{"redirect": agentflow.WithQuery(body["redirect_uri"], map[string]string{"error": "access_denied", "state": body["state"]})})
		return
	}
	if body["decision"] != "approve" {
		oauthFail(c, 400, "invalid_request", "decision must be approve or deny")
		return
	}
	code := s.flow().IssueCode(body["client_id"], p.AccountID, p.UserID, body["redirect_uri"], body["code_challenge"])
	c.JSON(http.StatusOK, gin.H{"redirect": agentflow.WithQuery(body["redirect_uri"], map[string]string{"code": code, "state": body["state"]})})
}

func (s *Server) oauthToken(c *gin.Context) {
	_ = c.Request.ParseForm()
	form := map[string]string{}
	if strings.Contains(c.GetHeader("Content-Type"), "application/json") {
		_ = c.ShouldBindJSON(&form)
	}
	for key, values := range c.Request.PostForm {
		if len(values) > 0 && form[key] == "" {
			form[key] = values[0]
		}
	}
	client, ok := s.flow().Client(strings.TrimSpace(form["client_id"]))
	if !ok || !s.flow().SecretOK(client, form["client_secret"]) {
		oauthFail(c, 401, "invalid_client", "unknown client")
		return
	}
	var issued map[string]any
	var err error
	switch strings.TrimSpace(form["grant_type"]) {
	case "authorization_code":
		issued, err = s.flow().ExchangeCode(form["code"], client.ID, form["redirect_uri"], form["code_verifier"])
	case "refresh_token":
		issued, err = s.flow().Refresh(form["refresh_token"], client.ID)
	default:
		oauthFail(c, 400, "unsupported_grant_type", "use authorization_code or refresh_token")
		return
	}
	if err != nil {
		oauthFail(c, 400, "invalid_grant", "code or refresh token was rejected")
		return
	}
	delete(issued, "grant_id")
	c.Header("Cache-Control", "no-store")
	c.JSON(http.StatusOK, issued)
}

func (s *Server) mcpPost(c *gin.Context) {
	origin := strings.TrimRight(s.publicURL(c), "/")
	token := bearerToken(c)
	grant, reason := s.flow().GrantForAccess(token)
	if reason != "" {
		c.Header("WWW-Authenticate", `Bearer realm="jobos", resource_metadata="`+origin+`/.well-known/oauth-protected-resource/mcp", scope="jobos"`)
		c.Header("Cache-Control", "no-store")
		c.JSON(http.StatusUnauthorized, gin.H{"error": reason})
		return
	}
	raw, err := c.GetRawData()
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"jsonrpc": "2.0", "error": gin.H{"code": -32700, "message": "parse error"}})
		return
	}
	var payload any
	if err := json.Unmarshal(raw, &payload); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"jsonrpc": "2.0", "error": gin.H{"code": -32700, "message": "parse error"}})
		return
	}
	batch, batchMode := payload.([]any)
	messages := []any{payload}
	if batchMode {
		messages = batch
	}
	headerSession := strings.TrimSpace(c.GetHeader("Mcp-Session-Id"))
	needsSession := false
	for _, item := range messages {
		msg, ok := item.(map[string]any)
		if !ok {
			continue
		}
		if strAny(msg["method"]) != "initialize" {
			needsSession = true
		}
	}
	if needsSession && (headerSession == "" || (grant.SessionID != "" && headerSession != grant.SessionID)) {
		c.JSON(http.StatusNotFound, gin.H{"error": "session not found"})
		return
	}
	session := s.flow().EnsureSession(grant)
	if needsSession && headerSession != session.ID {
		c.JSON(http.StatusNotFound, gin.H{"error": "session not found"})
		return
	}
	var replies []any
	for _, item := range messages {
		msg, ok := item.(map[string]any)
		if !ok {
			continue
		}
		if reply := s.handleRPC(c, grant, &session, msg); reply != nil {
			replies = append(replies, reply)
		}
	}
	c.Header("Mcp-Session-Id", session.ID)
	c.Header("Cache-Control", "no-store")
	if len(replies) == 0 {
		c.Status(http.StatusAccepted)
		return
	}
	if batchMode {
		c.JSON(http.StatusOK, replies)
		return
	}
	c.JSON(http.StatusOK, replies[0])
}

func (s *Server) mcpGet(c *gin.Context) {
	c.Header("Allow", "POST, DELETE")
	c.JSON(http.StatusMethodNotAllowed, gin.H{"error": "use POST for MCP"})
}

func (s *Server) mcpDelete(c *gin.Context) {
	grant, reason := s.flow().GrantForAccess(bearerToken(c))
	if reason != "" {
		origin := strings.TrimRight(s.publicURL(c), "/")
		c.Header("WWW-Authenticate", `Bearer realm="jobos", resource_metadata="`+origin+`/.well-known/oauth-protected-resource/mcp", scope="jobos"`)
		c.JSON(http.StatusUnauthorized, gin.H{"error": reason})
		return
	}
	supplied := strings.TrimSpace(c.GetHeader("Mcp-Session-Id"))
	if supplied != "" && supplied != grant.SessionID {
		c.JSON(http.StatusNotFound, gin.H{"error": "session not found"})
		return
	}
	if grant.SessionID != "" {
		s.flow().EndSession(grant.AccountID, grant.SessionID)
	}
	c.Status(http.StatusNoContent)
}

func (s *Server) connectPage(c *gin.Context) {
	if principalFrom(c).Role != "admin" {
		fail(c, 403, "admin only")
		return
	}
	origin := strings.TrimRight(s.publicURL(c), "/")
	page := "<!doctype html><title>Connect</title><h1>Connect an agent</h1><p>MCP URL</p><code>" + htmlEscape(origin+"/mcp") + "</code>" +
		"<p>Register at " + htmlEscape(origin+"/oauth/register") + ", then approve the client on this Hub.</p>"
	c.Data(http.StatusOK, "text/html; charset=utf-8", []byte(page))
}

func (s *Server) agentStatus(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" {
		fail(c, 403, "admin only")
		return
	}
	state := s.candidateState(c, p.AccountID)
	origin := strings.TrimRight(s.publicURL(c), "/")
	c.JSON(http.StatusOK, gin.H{
		"mcp_url": origin + "/mcp", "instructions": agentInstructions,
		"prompts": []string{"get started", "find jobs", "apply jobs", "outreach jobs"},
		"candidate_onboarded": state["onboarded"], "grants": s.flow().PublicGrants(p.AccountID),
		"connected": len(s.flow().PublicGrants(p.AccountID)) > 0,
		"uses": s.flow().Uses(), "steers": s.flow().Steers(p.AccountID),
	})
}

func (s *Server) agentSteer(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" {
		fail(c, 403, "admin only")
		return
	}
	var body struct {
		Body      string `json:"body"`
		SessionID string `json:"session_id"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	steer, err := s.flow().AddSteer(p.AccountID, p.UserID, body.Body, body.SessionID)
	if err != nil {
		fail(c, 422, err.Error())
		return
	}
	c.JSON(http.StatusCreated, steer)
}

func (s *Server) agentRevoke(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" {
		fail(c, 403, "admin only")
		return
	}
	if !s.flow().Revoke(p.AccountID, c.Param("id")) {
		fail(c, 404, "grant not found")
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (s *Server) handleRPC(c *gin.Context, grant agentflow.Grant, session *agentflow.AgentSession, msg map[string]any) any {
	method := strAny(msg["method"])
	id := msg["id"]
	params, _ := msg["params"].(map[string]any)
	if params == nil {
		params = map[string]any{}
	}
	if strings.HasPrefix(method, "notifications/") || (id == nil && method != "initialize") {
		return nil
	}
	switch method {
	case "initialize":
		if info, ok := params["clientInfo"].(map[string]any); ok {
			if name := strings.TrimSpace(strAny(info["name"])); name != "" {
				s.flow().SetLabel(session.ID, name)
				session.Label = name
			}
		}
		version := strAny(params["protocolVersion"])
		if version != "2025-06-18" && version != "2025-03-26" && version != "2024-11-05" {
			version = "2025-03-26"
		}
		return gin.H{"jsonrpc": "2.0", "id": id, "result": gin.H{
			"protocolVersion": version, "capabilities": gin.H{"tools": gin.H{"listChanged": false}},
			"serverInfo": gin.H{"name": "jobos", "version": "1.0.0"}, "instructions": agentInstructions,
		}}
	case "ping":
		return gin.H{"jsonrpc": "2.0", "id": id, "result": gin.H{}}
	case "tools/list":
		return gin.H{"jsonrpc": "2.0", "id": id, "result": gin.H{"tools": toolCatalog()}}
	case "tools/call":
		name := strAny(params["name"])
		args, _ := params["arguments"].(map[string]any)
		return gin.H{"jsonrpc": "2.0", "id": id, "result": s.callTool(c, grant, session, name, args)}
	default:
		return gin.H{"jsonrpc": "2.0", "id": id, "error": gin.H{"code": -32601, "message": "method not found: " + method}}
	}
}

func (s *Server) callTool(c *gin.Context, grant agentflow.Grant, session *agentflow.AgentSession, name string, args map[string]any) gin.H {
	if args == nil {
		args = map[string]any{}
	}
	fresh, ok := s.flow().Session(session.ID)
	if ok {
		*session = fresh
	}
	var payload any
	var err error
	switch name {
	case "get_started":
		payload = s.toolStarted(c, grant, *session)
	case "ask_session_lanes":
		payload = gin.H{"lanes": session.Lanes, "instruction": "Ask the human which of find, apply, and outreach this session should run. Then call set_session_lanes with the full set."}
	case "set_session_lanes":
		payload, err = s.toolSetLanes(session, args)
	case "report_capabilities":
		payload = s.toolCaps(session, args)
	case "evaluate_lane":
		payload = agentflow.EvaluateLane(viewOf(*session), strAny(args["lane"]))
	case "start_loop":
		payload, err = s.toolStartLoop(c, grant, *session, strAny(args["lane"]))
	case "next_loop":
		payload, err = s.toolNextLoop(c, grant, *session, strAny(args["loop_id"]))
	case "read_skill":
		payload, err = s.toolReadSkill(c, grant, strAny(args["skill"]))
	case "record_use":
		payload = s.flow().RecordUse(session.ID, strAny(args["kind"]), strAny(args["name"]))
	case "read_steers":
		payload = gin.H{"steers": s.flow().Steers(grant.AccountID)}
	case "recall_memory":
		payload, err = s.toolRecall(c, grant, args)
	case "write_memory":
		payload, err = s.toolWriteMemory(c, grant, args)
	case "list_jobs":
		payload, err = s.toolListJobs(c, grant, args)
	case "get_job":
		payload, err = s.toolGetJob(c, grant, strAny(args["id"]))
	case "create_job":
		payload, err = s.toolCreateJob(c, grant, *session, args)
	case "update_job":
		payload, err = s.toolUpdateJob(c, grant, *session, args)
	case "list_people":
		payload, err = s.toolPeople(c, grant, args)
	default:
		return toolResult(gin.H{"error": "unknown tool " + name}, true)
	}
	if err != nil {
		return toolResult(gin.H{"error": err.Error()}, true)
	}
	return toolResult(payload, false)
}

func (s *Server) toolStarted(c *gin.Context, grant agentflow.Grant, session agentflow.AgentSession) gin.H {
	state := s.candidateState(c, grant.AccountID)
	lanes := session.Lanes
	checks := map[string]any{}
	targets := lanes
	if len(targets) == 0 {
		targets = []string{"find", "apply", "outreach"}
	}
	for _, lane := range targets {
		checks[lane] = agentflow.EvaluateLane(viewOf(session), lane)
	}
	return gin.H{
		"prompts": []string{"get started", "find jobs", "apply jobs", "outreach jobs"},
		"session": session, "lane_checks": checks, "steers": s.flow().Steers(grant.AccountID),
		"loops": s.flow().Loops(session.ID),
		"candidate": gin.H{"onboarded": state["onboarded"], "resume_present": state["resume_present"], "missing": state["missing"], "onboarding_url": "/onboarding"},
		"instruction": "If lanes are empty, ask the human which lanes this session should run, then set_session_lanes. If capabilities are not reported, call report_capabilities before any lane.",
	}
}

func (s *Server) toolSetLanes(session *agentflow.AgentSession, args map[string]any) (gin.H, error) {
	raw, _ := args["lanes"].([]any)
	var lanes []string
	for _, item := range raw {
		lane := agentflow.NormalizeLane(strAny(item))
		if lane == "" {
			return nil, errString("lanes are find, apply, and outreach")
		}
		if !containsStr(lanes, lane) {
			lanes = append(lanes, lane)
		}
	}
	if len(lanes) == 0 {
		return nil, errString("pick at least one lane")
	}
	session.Lanes = lanes
	s.flow().UpdateSession(*session)
	return gin.H{"lanes": lanes}, nil
}

func (s *Server) toolCaps(session *agentflow.AgentSession, args map[string]any) gin.H {
	session.Capabilities = agentflow.Capabilities{Browser: truthy(args["browser"]), Email: truthy(args["email"]), Reported: true}
	s.flow().UpdateSession(*session)
	return gin.H{"capabilities": session.Capabilities}
}

func (s *Server) toolStartLoop(c *gin.Context, grant agentflow.Grant, session agentflow.AgentSession, lane string) (gin.H, error) {
	check := agentflow.EvaluateLane(viewOf(session), lane)
	if check["can"] != true {
		return nil, errString(strAny(check["instruction"]))
	}
	if err := s.requireOnboarded(c, grant.AccountID); err != nil {
		return nil, err
	}
	loop := s.flow().StartLoop(session.ID, strAny(check["lane"]))
	jobs, err := s.openJobs(c, grant.AccountID)
	if err != nil {
		return nil, err
	}
	step := agentflow.PlanLoop(loop.Lane, loop.ID, jobs)
	return gin.H{"loop": loop, "step": step}, nil
}

func (s *Server) toolNextLoop(c *gin.Context, grant agentflow.Grant, session agentflow.AgentSession, loopID string) (gin.H, error) {
	var loop agentflow.Loop
	found := false
	for _, item := range s.flow().Loops(session.ID) {
		if item.ID == loopID {
			loop = item
			found = true
		}
	}
	if !found {
		return nil, errString("loop not found")
	}
	check := agentflow.EvaluateLane(viewOf(session), loop.Lane)
	if check["can"] != true {
		return nil, errString(strAny(check["instruction"]))
	}
	jobs, err := s.openJobs(c, grant.AccountID)
	if err != nil {
		return nil, err
	}
	step := agentflow.PlanLoop(loop.Lane, loop.ID, jobs)
	if step["continue"] == false {
		s.flow().SetLoopStatus(loop.ID, strAny(step["status"]))
	}
	return gin.H{"loop_id": loop.ID, "step": step}, nil
}

func (s *Server) toolReadSkill(c *gin.Context, grant agentflow.Grant, name string) (gin.H, error) {
	skills, err := s.DB.ListSkills(c.Request.Context(), grant.AccountID, "", "", "")
	if err != nil {
		return nil, err
	}
	for _, skill := range skills {
		if skill.Slug == name || skill.Name == name || skill.ID == name {
			return gin.H{"id": skill.ID, "slug": skill.Slug, "name": skill.Name, "body": skill.Body, "role": skill.Role}, nil
		}
	}
	return nil, errString("skill not found")
}

func (s *Server) toolRecall(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	items, err := s.DB.ListMemory(c.Request.Context(), grant.AccountID, strAny(args["pod"]))
	if err != nil {
		return nil, err
	}
	q := strings.ToLower(strAny(args["q"]))
	var kept []store.MemoryItem
	for _, item := range items {
		if q == "" || strings.Contains(strings.ToLower(item.Title+" "+item.Body), q) {
			kept = append(kept, item)
		}
	}
	if kept == nil {
		kept = []store.MemoryItem{}
	}
	return gin.H{"items": kept}, nil
}

func (s *Server) toolWriteMemory(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	body := strings.TrimSpace(strAny(args["body"]))
	kind := strings.TrimSpace(strAny(args["kind"]))
	if body == "" || kind == "" {
		return nil, errString("kind and body are required")
	}
	item := store.MemoryItem{
		ID: "mem_" + random(6), AccountID: grant.AccountID, Pod: strAny(args["pod"]),
		Kind: kind, Title: strAny(args["title"]), Body: body, JobID: strAny(args["job_id"]),
		Company: strAny(args["company"]), CreatedAt: now(), UpdatedAt: now(), SolidifyStatus: "none",
	}
	if item.Pod == "" {
		item.Pod = "common"
	}
	if err := s.DB.SaveMemory(c.Request.Context(), item); err != nil {
		return nil, err
	}
	return gin.H{"item": item}, nil
}

func (s *Server) toolListJobs(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	jobs, _, _, err := s.DB.ListJobs(c.Request.Context(), store.JobFilter{AccountID: grant.AccountID, Status: strAny(args["status"]), Limit: 50})
	if err != nil {
		return nil, err
	}
	if jobs == nil {
		jobs = []store.Job{}
	}
	return gin.H{"jobs": jobs}, nil
}

func (s *Server) toolGetJob(c *gin.Context, grant agentflow.Grant, id string) (gin.H, error) {
	job, err := s.DB.Job(c.Request.Context(), grant.AccountID, id)
	if err != nil {
		return nil, errString("job not found")
	}
	return gin.H{"job": job}, nil
}

func (s *Server) toolCreateJob(c *gin.Context, grant agentflow.Grant, session agentflow.AgentSession, args map[string]any) (gin.H, error) {
	if err := gateLane(session, "find"); err != nil {
		return nil, err
	}
	if err := s.requireOnboarded(c, grant.AccountID); err != nil {
		return nil, err
	}
	company := strings.TrimSpace(strAny(args["company"]))
	title := strings.TrimSpace(strAny(args["title"]))
	if company == "" || title == "" {
		return nil, errString("company and title are required")
	}
	id := strAny(args["id"])
	if id == "" {
		id = slug(company, title)
	}
	j := store.Job{AccountID: grant.AccountID, ID: id, Company: company, Title: title, Status: "discovered", URL: strAny(args["url"]), ApplyURL: strAny(args["apply_url"]), Location: strAny(args["location"]), CreatedAt: now(), UpdatedAt: now(), CreatedByRole: "discovery", Sources: json.RawMessage("[]")}
	if err := s.DB.SaveJob(c.Request.Context(), j); err != nil {
		return nil, err
	}
	return gin.H{"job": j}, nil
}

func (s *Server) toolUpdateJob(c *gin.Context, grant agentflow.Grant, session agentflow.AgentSession, args map[string]any) (gin.H, error) {
	lane := agentflow.NormalizeLane(strAny(args["lane"]))
	if lane == "" {
		lane = "apply"
	}
	if err := gateLane(session, lane); err != nil {
		return nil, err
	}
	job, err := s.DB.Job(c.Request.Context(), grant.AccountID, strAny(args["id"]))
	if err != nil {
		return nil, errString("job not found")
	}
	if status := strAny(args["status"]); status != "" {
		job.Status = status
	}
	if notes := strAny(args["notes"]); notes != "" {
		job.Notes = notes
	}
	job.UpdatedAt = now()
	if err := s.DB.SaveJob(c.Request.Context(), job); err != nil {
		return nil, err
	}
	return gin.H{"job": job}, nil
}

func (s *Server) toolPeople(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	people, err := s.DB.ListPeople(c.Request.Context(), grant.AccountID, strAny(args["company"]), strAny(args["job_id"]))
	if err != nil {
		return nil, err
	}
	if people == nil {
		people = []store.Person{}
	}
	return gin.H{"people": people}, nil
}

func (s *Server) openJobs(c *gin.Context, accountID string) ([]agentflow.JobView, error) {
	stopped := false
	jobs, _, _, err := s.DB.ListJobs(c.Request.Context(), store.JobFilter{AccountID: accountID, Stopped: &stopped, Limit: 200})
	if err != nil {
		return nil, err
	}
	out := make([]agentflow.JobView, 0, len(jobs))
	for _, job := range jobs {
		var sources []string
		_ = json.Unmarshal(job.Sources, &sources)
		out = append(out, agentflow.JobView{ID: job.ID, Status: job.Status, Stopped: job.Stopped, Sources: sources, Company: job.Company, Title: job.Title})
	}
	return out, nil
}

func (s *Server) requireOnboarded(c *gin.Context, accountID string) error {
	state := s.candidateState(c, accountID)
	if state["onboarded"] != true {
		return errString("The candidate profile is not onboarded. Tell the human to finish /onboarding. Do not invent one.")
	}
	return nil
}

func gateLane(session agentflow.AgentSession, lane string) error {
	check := agentflow.EvaluateLane(viewOf(session), lane)
	if check["can"] != true {
		return errString(strAny(check["instruction"]))
	}
	return nil
}

func viewOf(session agentflow.AgentSession) agentflow.SessionView {
	return agentflow.SessionView{Lanes: session.Lanes, Capabilities: session.Capabilities}
}

func toolResult(payload any, isError bool) gin.H {
	raw, _ := json.MarshalIndent(payload, "", "  ")
	return gin.H{"content": []gin.H{{"type": "text", "text": string(raw)}}, "isError": isError}
}

func toolCatalog() []gin.H {
	lane := gin.H{"type": "string", "enum": []string{"find", "apply", "outreach"}}
	obj := func(props gin.H, required ...string) gin.H {
		body := gin.H{"type": "object", "properties": props, "additionalProperties": false}
		if len(required) > 0 {
			body["required"] = required
		}
		return body
	}
	return []gin.H{
		{"name": "get_started", "description": "First call after connect.", "inputSchema": obj(gin.H{})},
		{"name": "ask_session_lanes", "description": "Ask which lanes this session runs.", "inputSchema": obj(gin.H{})},
		{"name": "set_session_lanes", "description": "Store the lanes the human chose.", "inputSchema": obj(gin.H{"lanes": gin.H{"type": "array", "items": lane}}, "lanes")},
		{"name": "report_capabilities", "description": "Report browser and email for this client.", "inputSchema": obj(gin.H{"browser": gin.H{"type": "boolean"}, "email": gin.H{"type": "boolean"}}, "browser", "email")},
		{"name": "evaluate_lane", "description": "Check whether this session can run a lane.", "inputSchema": obj(gin.H{"lane": lane}, "lane")},
		{"name": "start_loop", "description": "Start a find, apply, or outreach loop.", "inputSchema": obj(gin.H{"lane": lane}, "lane")},
		{"name": "next_loop", "description": "Take the next step of a loop.", "inputSchema": obj(gin.H{"loop_id": gin.H{"type": "string"}}, "loop_id")},
		{"name": "read_skill", "description": "Read a skill body.", "inputSchema": obj(gin.H{"skill": gin.H{"type": "string"}}, "skill")},
		{"name": "record_use", "description": "Record a tool or source you used.", "inputSchema": obj(gin.H{"kind": gin.H{"type": "string"}, "name": gin.H{"type": "string"}}, "kind", "name")},
		{"name": "read_steers", "description": "Read human steers.", "inputSchema": obj(gin.H{})},
		{"name": "recall_memory", "description": "Recall memory for this account.", "inputSchema": obj(gin.H{"q": gin.H{"type": "string"}, "pod": gin.H{"type": "string"}})},
		{"name": "write_memory", "description": "Write a memory item.", "inputSchema": obj(gin.H{"kind": gin.H{"type": "string"}, "body": gin.H{"type": "string"}}, "kind", "body")},
		{"name": "list_jobs", "description": "List jobs.", "inputSchema": obj(gin.H{"status": gin.H{"type": "string"}})},
		{"name": "get_job", "description": "Read one job.", "inputSchema": obj(gin.H{"id": gin.H{"type": "string"}}, "id")},
		{"name": "create_job", "description": "Create a discovered job. Find lane only.", "inputSchema": obj(gin.H{"company": gin.H{"type": "string"}, "title": gin.H{"type": "string"}}, "company", "title")},
		{"name": "update_job", "description": "Update a job from the lane that owns the status.", "inputSchema": obj(gin.H{"id": gin.H{"type": "string"}, "lane": lane, "status": gin.H{"type": "string"}}, "id")},
		{"name": "list_people", "description": "List people.", "inputSchema": obj(gin.H{"company": gin.H{"type": "string"}, "job_id": gin.H{"type": "string"}})},
	}
}

func oauthFail(c *gin.Context, code int, err, description string) {
	c.Header("Cache-Control", "no-store")
	c.JSON(code, gin.H{"error": err, "error_description": description})
}

func containsStr(items []string, want string) bool {
	for _, item := range items {
		if item == want {
			return true
		}
	}
	return false
}

func strAny(v any) string {
	s, _ := v.(string)
	return s
}

func truthy(v any) bool {
	b, _ := v.(bool)
	return b
}

func htmlEscape(s string) string {
	r := strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;", `"`, "&quot;")
	return r.Replace(s)
}

type errString string

func (e errString) Error() string { return string(e) }
