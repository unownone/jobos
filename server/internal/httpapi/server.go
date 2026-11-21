package httpapi

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
	"unicode"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"

	"github.com/unownone/jobos/server/internal/agentflow"
	"github.com/unownone/jobos/server/internal/blob"
	"github.com/unownone/jobos/server/internal/cache"
	"github.com/unownone/jobos/server/internal/config"
	"github.com/unownone/jobos/server/internal/realtime"
	"github.com/unownone/jobos/server/internal/store"
	"github.com/unownone/jobos/server/internal/telemetry"
)

const (
	cookieSession = "hub_session"
	cookieCSRF    = "hub_csrf"
	candidateKey  = "candidate.yaml"
	resumeKey     = "candidate-resume.pdf"
)

type Server struct {
	Cfg   config.Config
	DB    store.Store
	Blobs blob.Store
	Cache cache.Cache
	RT    *realtime.Hub
	Flow  *agentflow.Flow
}

func New(cfg config.Config, db store.Store, blobs blob.Store, c cache.Cache, rt *realtime.Hub) *Server {
	return &Server{Cfg: cfg, DB: db, Blobs: blobs, Cache: c, RT: rt, Flow: agentflow.New()}
}

type principal struct {
	Role      string
	Actor     string
	UserID    string
	Track     string
	Kind      string
	Auth      string
	AccountID string
	SessionID string
}

func (s *Server) Router() *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(telemetry.GinRecovery(), telemetry.GinRequest())
	r.Use(func(c *gin.Context) {
		c.Header("Access-Control-Allow-Origin", c.GetHeader("Origin"))
		c.Header("Access-Control-Allow-Credentials", "true")
		c.Header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-CSRF, X-Role, X-Token, X-Actor, X-Hub-Key, Mcp-Session-Id, MCP-Protocol-Version")
		c.Header("Access-Control-Expose-Headers", "Mcp-Session-Id, WWW-Authenticate")
		c.Header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
		if c.Request.Method == http.MethodOptions {
			c.Status(http.StatusNoContent)
			c.Abort()
			return
		}
		c.Next()
	})

	r.GET("/health", s.health)
	r.GET("/ready", s.ready)
	r.GET("/llms.txt", s.briefing("llms.txt"))
	r.GET("/.well-known/llms.txt", s.briefing("llms.txt"))
	r.GET("/agents.txt", s.briefing("agents.txt"))
	r.GET("/.well-known/agents.txt", s.briefing("agents.txt"))
	r.GET("/.well-known/agent-card.json", s.agentCard(""))
	r.GET("/.well-known/agent.json", s.agentCard(""))
	r.GET("/a2a/agent-card.json", s.agentCard(""))
	r.GET("/a2a/:track/agent-card.json", func(c *gin.Context) { s.agentCard(c.Param("track"))(c) })
	r.GET("/a2a/:track/.well-known/agent-card.json", func(c *gin.Context) { s.agentCard(c.Param("track"))(c) })
	r.GET("/api/candidate/public", s.candidatePublic)
	r.GET("/api/candidate/status", s.candidateStatus)
	r.GET("/api/candidate/template", s.candidateTemplate)
	r.GET("/api/registry/catalog", s.catalog)
	r.POST("/api/auth/bootstrap", s.bootstrap)
	r.POST("/api/auth/signup", s.signup)
	r.POST("/api/auth/login", s.login)
	r.GET("/api/join/:id", s.joinPreview)
	r.POST("/api/auth/join", s.join)
	r.POST("/a2a", s.a2a)
	r.POST("/a2a/:track", s.a2a)
	r.GET("/a2a", s.a2aInfo)
	s.mountAgent(r)

	authed := r.Group("/")
	authed.Use(s.requireAuth, s.candidateGate)
	authed.POST("/api/auth/logout", s.logout)
	authed.GET("/api/auth/me", s.me)
	authed.GET("/api/whoami", s.me)
	authed.GET("/api/meta", s.meta)
	authed.GET("/api/jobs", s.listJobs)
	authed.POST("/api/jobs", s.createJob)
	authed.GET("/api/jobs/:id", s.getJob)
	authed.PATCH("/api/jobs/:id", s.patchJob)
	authed.DELETE("/api/jobs/:id", s.deleteJob)
	authed.POST("/api/jobs/:id/stop", s.stopJob)
	authed.POST("/api/jobs/:id/pause", s.pauseJob)
	authed.POST("/api/jobs/:id/resume", s.resumeJob)
	authed.GET("/api/events", s.listEvents)
	authed.GET("/api/hygiene", s.hygiene)
	authed.POST("/api/hygiene/vacuum", s.vacuum)
	authed.POST("/api/import", s.importJobs)
	authed.GET("/api/export/ledger", s.exportLedger)
	authed.GET("/api/dashboard", s.dashboard)
	authed.POST("/api/invites", s.createInvite)
	authed.GET("/api/invites", s.listInvites)
	authed.POST("/api/invites/:id/revoke", s.revokeInvite)
	authed.GET("/api/agents", s.listAgents)
	authed.POST("/api/agents", s.createAgent)
	authed.POST("/api/agents/:id/rotate_key", s.rotateKey)
	authed.POST("/api/agents/:id/disable", s.disableAgent)
	authed.GET("/api/candidate", s.getCandidate)
	authed.PUT("/api/candidate", s.putCandidate)
	authed.GET("/api/candidate/resume", s.getResume)
	authed.PUT("/api/candidate/resume", s.putResume)
	authed.POST("/api/queue/push", s.queuePush)
	authed.POST("/api/queue/claim", s.queueClaim)
	authed.POST("/api/queue/ack/:id", s.queueAck)
	authed.POST("/api/queue/nack/:id", s.queueNack)
	authed.GET("/api/queue/mine", s.queueMine)
	authed.GET("/api/queue", s.queueList)
	authed.GET("/api/people", s.listPeople)
	authed.POST("/api/people", s.createPerson)
	authed.GET("/api/people/:id", s.getPerson)
	authed.PATCH("/api/people/:id", s.patchPerson)
	authed.GET("/api/memory/pods", s.memoryPods)
	authed.GET("/api/memory/recall", s.memoryRecall)
	authed.GET("/api/memory/items", s.listMemory)
	authed.POST("/api/memory/items", s.createMemory)
	authed.PATCH("/api/memory/items/:id", s.patchMemory)
	authed.DELETE("/api/memory/items/:id", s.deleteMemory)
	authed.POST("/api/memory/items/:id/solidify", s.solidifyMemory)
	authed.POST("/api/memory/items/:id/move", s.moveMemory)
	authed.POST("/api/messages", s.createMessage)
	authed.GET("/api/messages", s.listMessages)
	authed.POST("/api/messages/:id/read", s.readMessage)
	authed.POST("/api/presence/heartbeat", s.heartbeat)
	authed.GET("/api/presence", s.listPresence)
	authed.GET("/api/presence/:id", s.getPresence)
	authed.GET("/api/users", s.listUsers)
	authed.GET("/api/registry/skills", s.listSkills)
	authed.GET("/api/registry/skills/:id", s.getSkill)
	authed.PATCH("/api/registry/skills/:id", s.patchSkill)
	authed.POST("/api/registry/skills", s.createSkill)
	authed.POST("/api/registry/recordings", s.createRecording)
	authed.GET("/api/registry/recordings", s.listRecordings)
	authed.GET("/api/registry/recordings/:id", s.getRecording)
	authed.POST("/api/registry/recordings/:id/proctor", s.proctorRecording)
	authed.POST("/api/registry/recordings/:id/promote", s.promoteRecording)
	authed.POST("/api/registry/recordings/:id/decline", s.declineRecording)
	authed.POST("/api/registry/seed", s.seedSkills)
	authed.POST("/api/registry/skills/:id/fork", s.forkSkill)
	authed.GET("/api/registry/mcps", s.listMCPs)
	authed.GET("/api/registry/mcps/:id", s.getMCP)
	authed.GET("/api/onboarding", s.onboarding)
	authed.GET("/api/docs/*path", s.getDoc)
	authed.GET("/api/skills/:name/*file", s.getSkillFile)
	authed.GET("/api/mcp/example.json", func(c *gin.Context) { s.sendRepo(c, "mcp/mcp.example.json") })
	authed.GET("/api/mcp/hosted/*name", func(c *gin.Context) {
		s.sendRepo(c, "mcp/hosted/"+strings.TrimPrefix(c.Param("name"), "/"))
	})
	authed.GET("/api/scripts/:name", func(c *gin.Context) { s.sendRepo(c, "scripts/"+c.Param("name")) })
	authed.GET("/api/packs/current/skills.zip", s.skillsZip)
	authed.POST("/api/packs/rebuild", s.rebuildPack)
	authed.POST("/api/metrics/token_burn", s.addBurn)
	authed.GET("/api/metrics/token_burn", s.listBurns)
	authed.GET("/api/metrics/summary", s.burnSummary)
	authed.GET("/api/a2a/directory", s.a2aDirectory)
	authed.GET("/api/a2a/peers", s.listPeers)
	authed.POST("/api/a2a/peers", s.createPeer)
	authed.POST("/api/a2a/peers/:id/send", s.sendPeer)
	authed.GET("/api/stream", s.stream)
	authed.GET("/ws", s.socket)
	s.serveSPA(r)
	return r
}

func (s *Server) serveSPA(r *gin.Engine) {
	root := strings.TrimSpace(s.Cfg.WebRoot)
	if root == "" {
		return
	}
	r.NoRoute(func(c *gin.Context) {
		if c.Request.Method != http.MethodGet && c.Request.Method != http.MethodHead {
			c.Status(http.StatusNotFound)
			return
		}
		path := c.Request.URL.Path
		if strings.HasPrefix(path, "/api/") || path == "/api" || strings.HasPrefix(path, "/a2a") || strings.HasPrefix(path, "/ws") || strings.HasPrefix(path, "/.well-known/") {
			c.Status(http.StatusNotFound)
			return
		}
		file, ok := spaFile(root, path)
		if !ok {
			c.Status(http.StatusNotFound)
			return
		}
		c.File(file)
	})
}

func spaFile(root, urlPath string) (string, bool) {
	rootAbs, err := filepath.Abs(root)
	if err != nil {
		return "", false
	}
	rel := strings.TrimPrefix(filepath.Clean("/"+urlPath), "/")
	full := filepath.Join(rootAbs, rel)
	fullAbs, err := filepath.Abs(full)
	if err != nil || (fullAbs != rootAbs && !strings.HasPrefix(fullAbs, rootAbs+string(os.PathSeparator))) {
		return "", false
	}
	if info, err := os.Stat(fullAbs); err == nil && !info.IsDir() {
		return fullAbs, true
	}
	index := filepath.Join(rootAbs, "index.html")
	if _, err := os.Stat(index); err != nil {
		return "", false
	}
	return index, true
}

func (s *Server) requireAuth(c *gin.Context) {
	p, err := s.authenticate(c)
	if err != nil {
		status := http.StatusUnauthorized
		var he *httpError
		if errors.As(err, &he) {
			status = he.code
		}
		telemetry.HTTPFail(status, err.Error(), "http.method", c.Request.Method, "http.route", c.Request.URL.Path)
		c.AbortWithStatusJSON(status, gin.H{"detail": err.Error()})
		return
	}
	c.Set("principal", p)
	c.Next()
}

type httpError struct {
	code int
	msg  string
}

func (e *httpError) Error() string { return e.msg }

func fail(c *gin.Context, code int, msg string) {
	attrs := []any{}
	if c != nil && c.Request != nil {
		attrs = append(attrs, "http.method", c.Request.Method, "http.route", c.Request.URL.Path)
	}
	telemetry.HTTPFail(code, msg, attrs...)
	c.JSON(code, gin.H{"detail": msg})
}

func principalFrom(c *gin.Context) principal {
	v, _ := c.Get("principal")
	p, _ := v.(principal)
	return p
}

func (s *Server) authenticate(c *gin.Context) (principal, error) {
	bearer := bearerToken(c)
	if bearer != "" {
		if strings.HasPrefix(bearer, "jh_boot_") || strings.HasPrefix(bearer, "jh_inv_") {
			return principal{}, &httpError{http.StatusUnauthorized, "this key cannot authenticate API calls"}
		}
		if p, ok := s.cachedPrincipal(c, bearer); ok {
			return p, nil
		}
		key, err := s.DB.APIKeyByHash(c.Request.Context(), hash(bearer))
		if err != nil || key.RevokedAt != "" {
			return principal{}, &httpError{http.StatusUnauthorized, "invalid API key"}
		}
		user, err := s.DB.User(c.Request.Context(), key.UserID)
		if err != nil || user.DisabledAt != "" {
			return principal{}, &httpError{http.StatusUnauthorized, "invalid API key"}
		}
		s.storeKey(c, bearer, user)
		return principalFromUser(user, authKind(user.Kind), c.GetHeader("X-Actor")), nil
	}
	role := strings.ToLower(strings.TrimSpace(c.GetHeader("X-Role")))
	token := strings.TrimSpace(c.GetHeader("X-Token"))
	if role != "" && token != "" {
		expected := s.Cfg.CompatTokens[role]
		if expected == "" {
			return principal{}, &httpError{http.StatusServiceUnavailable, "role token is not configured"}
		}
		if !constEq(token, expected) {
			return principal{}, &httpError{http.StatusUnauthorized, "invalid token for role"}
		}
		track := map[string]string{"discovery": "discovery", "apply": "application", "outreach": "outreach", "maintenance": "maintenance"}[role]
		return principal{
			Role: role, Actor: c.GetHeader("X-Actor"), Track: track, Kind: "compat", Auth: "compat_role", AccountID: "acc_compat",
		}, nil
	}
	raw, err := c.Cookie(cookieSession)
	if err != nil || raw == "" {
		return principal{}, &httpError{http.StatusUnauthorized, "missing credentials"}
	}
	if p, ok := s.cachedSession(c, raw); ok {
		return p, nil
	}
	sess, err := s.DB.SessionByHash(c.Request.Context(), hash(raw))
	if err != nil {
		return principal{}, &httpError{http.StatusUnauthorized, "invalid session"}
	}
	if sess.ExpiresAt < now() {
		_ = s.DB.DeleteSession(c.Request.Context(), sess.ID)
		return principal{}, &httpError{http.StatusUnauthorized, "session expired"}
	}
	if c.Request.Method != http.MethodGet && c.Request.Method != http.MethodHead {
		csrfCookie, _ := c.Cookie(cookieCSRF)
		header := c.GetHeader("X-CSRF")
		if csrfCookie == "" || header == "" || !constEq(csrfCookie, header) || sess.CSRFHash != hash(header) {
			return principal{}, &httpError{http.StatusForbidden, "missing or invalid X-CSRF"}
		}
	}
	user, err := s.DB.User(c.Request.Context(), sess.UserID)
	if err != nil || user.DisabledAt != "" {
		return principal{}, &httpError{http.StatusUnauthorized, "invalid session"}
	}
	s.storeSession(c, raw, sess, user)
	p := principalFromUser(user, "session", "")
	p.SessionID = sess.ID
	return p, nil
}

func authKind(kind string) string {
	switch kind {
	case "admin":
		return "admin_key"
	case "owner":
		return "owner_key"
	default:
		return "agent_key"
	}
}

func principalFromUser(u store.User, auth, actor string) principal {
	role := "maintenance"
	track := u.Track
	switch u.Kind {
	case "admin":
		role, track = "admin", ""
	case "owner", "agent":
		role = map[string]string{"discovery": "discovery", "application": "apply", "outreach": "outreach", "maintenance": "maintenance"}[u.Track]
	}
	if actor == "" {
		actor = u.DisplayName
		if actor == "" {
			actor = u.Email
		}
	}
	return principal{Role: role, Actor: actor, UserID: u.ID, Track: track, Kind: u.Kind, Auth: auth, AccountID: u.AccountID}
}

func bearerToken(c *gin.Context) string {
	if v := strings.TrimSpace(c.GetHeader("X-Hub-Key")); v != "" {
		return v
	}
	h := strings.TrimSpace(c.GetHeader("Authorization"))
	if len(h) > 7 && strings.EqualFold(h[:7], "bearer ") {
		return strings.TrimSpace(h[7:])
	}
	if q := strings.TrimSpace(c.Query("access_token")); q != "" {
		return q
	}
	return ""
}

func (s *Server) candidateGate(c *gin.Context) {
	if openWithoutCandidate(c.Request.URL.Path) {
		c.Next()
		return
	}
	p := principalFrom(c)
	if p.AccountID == "" || p.AccountID == "acc_compat" {
		c.Next()
		return
	}
	if s.onboarded(c, p.AccountID) {
		c.Next()
		return
	}
	c.AbortWithStatusJSON(http.StatusConflict, gin.H{"detail": candidateRequiredBody()})
}

func candidateRequiredBody() gin.H {
	return gin.H{
		"code":           "candidate_required",
		"message":        "Onboard the candidate profile before using the Hub. Do not invent one.",
		"onboarding_url": "/onboarding",
	}
}

func openWithoutCandidate(path string) bool {
	switch path {
	case "/api/auth/logout", "/api/auth/me", "/api/whoami", "/api/candidate", "/api/candidate/resume", "/api/candidate/public", "/api/candidate/status", "/api/candidate/template", "/api/registry/catalog":
		return true
	default:
		return false
	}
}

func (s *Server) onboarded(c *gin.Context, accountID string) bool {
	key := "cand:" + accountID
	if raw, ok, err := s.Cache.Get(c.Request.Context(), key); err == nil && ok {
		return len(raw) == 1 && raw[0] == '1'
	}
	obj, err := s.Blobs.Get(c.Request.Context(), accountID, candidateKey)
	on := err == nil && profileMissing(string(obj.Content)) == ""
	val := []byte("0")
	if on {
		val = []byte("1")
	}
	_ = s.Cache.Set(c.Request.Context(), key, val, candidateTTL)
	return on
}

func realCandidate(text string) bool {
	return profileMissing(text) == ""
}

func (s *Server) setSession(c *gin.Context, user store.User) {
	token := "sess_" + random(24)
	csrf := random(18)
	_ = s.DB.CreateSession(c.Request.Context(), store.Session{
		ID: newID("ses_"), AccountID: user.AccountID, UserID: user.ID,
		TokenHash: hash(token), CSRFHash: hash(csrf),
		ExpiresAt: time.Now().UTC().Add(14 * 24 * time.Hour).Format(time.RFC3339),
		LastSeen:  now(),
	})
	secure := strings.HasPrefix(s.Cfg.PublicURL, "https://")
	c.SetCookie(cookieSession, token, 14*24*3600, "/", "", secure, true)
	c.SetCookie(cookieCSRF, csrf, 14*24*3600, "/", "", secure, false)
	c.Header("X-CSRF", csrf)
}

func hash(s string) string {
	sum := sha256.Sum256([]byte(s))
	return hex.EncodeToString(sum[:])
}

func random(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

func newID(prefix string) string { return prefix + random(8) }

func now() string { return time.Now().UTC().Format(time.RFC3339) }

func constEq(a, b string) bool {
	if len(a) != len(b) {
		return false
	}
	var v byte
	for i := 0; i < len(a); i++ {
		v |= a[i] ^ b[i]
	}
	return v == 0
}

func (s *Server) health(c *gin.Context) {
	c.JSON(http.StatusOK, s.healthBody(c, false))
}

func (s *Server) ready(c *gin.Context) {
	body := s.healthBody(c, true)
	code := http.StatusOK
	if body["db"] != true {
		code = http.StatusServiceUnavailable
	}
	c.JSON(code, body)
}

func (s *Server) healthBody(c *gin.Context, ready bool) gin.H {
	dbOK := s.DB.Ping(c.Request.Context()) == nil
	admin, err := s.DB.FirstAdmin(c.Request.Context())
	boot := err == nil && admin.ID != ""
	account := ""
	if boot {
		account = admin.AccountID
	}
	state := s.candidateState(c, account)
	next := state["next_step"]
	if !boot {
		next = "signup"
	}
	roles := make([]string, 0, len(s.Cfg.CompatTokens))
	for role := range s.Cfg.CompatTokens {
		roles = append(roles, role)
	}
	sort.Strings(roles)
	allRoles := map[string]bool{"discovery": true, "apply": true, "outreach": true, "admin": true, "maintenance": true}
	for _, role := range roles {
		delete(allRoles, role)
	}
	body := gin.H{
		"ok": true, "db": dbOK, "store": s.DB.Name(), "cache": s.Cache.Name(), "blob": s.Blobs.Name(),
		"queue": "postgres-table", "rabbitmq": false,
		"roles_configured": roles, "all_roles_configured": len(allRoles) == 0,
		"admin_bootstrapped": boot, "candidate_onboarded": state["onboarded"],
		"resume_present": state["resume_present"], "ready_for_agents": boot && state["ready_for_agents"] == true,
		"next_step": next,
	}
	if ready {
		body["ready"] = dbOK
		if !dbOK {
			body["ok"] = false
		}
	}
	return body
}

func (s *Server) candidateState(c *gin.Context, account string) gin.H {
	present := false
	onboarded := false
	resume := false
	source := "missing"
	if account != "" {
		if obj, err := s.Blobs.Get(c.Request.Context(), account, candidateKey); err == nil && len(obj.Content) > 0 {
			present = true
			source = "blob"
			onboarded = realCandidate(string(obj.Content))
		}
		if _, err := s.Blobs.Get(c.Request.Context(), account, resumeKey); err == nil {
			resume = true
		}
	}
	next := "onboarding"
	if onboarded && resume {
		next = "ready"
	} else if onboarded {
		next = "resume"
	}
	missing := []string{}
	if !onboarded {
		missing = []string{"name"}
	}
	return gin.H{
		"present": present, "onboarded": onboarded, "resume_present": resume,
		"ready_for_agents": onboarded && resume, "missing": missing,
		"onboarding_url": "/onboarding", "next_step": next, "source": source,
	}
}

func (s *Server) briefing(name string) gin.HandlerFunc {
	return func(c *gin.Context) {
		body := fallbackBriefing(name, s.publicURL(c))
		if s.Cfg.RepoRoot != "" {
			if raw, err := os.ReadFile(s.Cfg.RepoRoot + "/" + name); err == nil {
				body = strings.ReplaceAll(string(raw), "{{HUB_URL}}", s.publicURL(c))
			}
		}
		c.Data(http.StatusOK, "text/plain; charset=utf-8", []byte(body))
	}
}

func (s *Server) publicURL(c *gin.Context) string {
	if s.Cfg.PublicURL != "" {
		return s.Cfg.PublicURL
	}
	return "http://" + c.Request.Host
}

func fallbackBriefing(name, hub string) string {
	if name == "agents.txt" {
		return "jobOS agent playbook\nHub: " + hub + "\nCurl " + hub + "/llms.txt then join with POST /api/auth/join.\n"
	}
	return "jobOS\nHub origin: " + hub + "\nGET /health  GET /api/candidate/public  GET /api/registry/catalog\n"
}

func (s *Server) agentCard(track string) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"name": "jobOS", "protocolVersion": "0.3.0", "track": track,
			"url": s.publicURL(c) + "/a2a",
		})
	}
}

func (s *Server) a2aInfo(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"protocol": "a2a", "jsonrpc": "/a2a", "version": "0.3.0"})
}

func (s *Server) bootstrap(c *gin.Context) {
	if s.Cfg.BootstrapToken == "" {
		fail(c, 404, "bootstrap is not configured")
		return
	}
	var body struct {
		Token     string `json:"token"`
		Bootstrap string `json:"bootstrap"`
		Email     string `json:"email"`
		Password  string `json:"password"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	token := strings.TrimSpace(body.Token)
	if token == "" {
		token = strings.TrimSpace(body.Bootstrap)
	}
	if auth := c.GetHeader("Authorization"); strings.HasPrefix(strings.ToLower(auth), "bearer ") {
		token = strings.TrimSpace(auth[7:])
	}
	for _, header := range []string{"X-Hub-Key", "X-Bootstrap-Token"} {
		if value := strings.TrimSpace(c.GetHeader(header)); value != "" {
			token = value
		}
	}
	used, _ := s.DB.GetKV(c.Request.Context(), "bootstrap.used")
	if used == "1" {
		fail(c, 403, "signup closed; log in")
		return
	}
	expected := s.Cfg.BootstrapToken
	if !strings.HasPrefix(token, "jh_boot_") && strings.HasPrefix(expected, "jh_boot_") {
		token = "jh_boot_" + token
	}
	if subtle.ConstantTimeCompare([]byte(token), []byte(expected)) != 1 {
		fail(c, 403, "invalid or used bootstrap token")
		return
	}
	email := strings.ToLower(strings.TrimSpace(body.Email))
	if !strings.Contains(email, "@") || len(body.Password) < 8 {
		fail(c, 422, "email and password are required")
		return
	}
	username := strings.Map(func(r rune) rune {
		if unicode.IsLetter(r) || unicode.IsDigit(r) || r == '.' || r == '_' || r == '-' {
			return r
		}
		return -1
	}, strings.Split(email, "@")[0])
	if len(username) < 3 {
		username = "admin" + newID("")[:8]
	}
	if _, _, err := s.DB.AccountByUsername(c.Request.Context(), username); err == nil {
		username = username + newID("")[:6]
	}
	pw, err := hashPassword(body.Password)
	if err != nil {
		fail(c, 500, "could not hash password")
		return
	}
	acc := store.Account{ID: newID("acc_"), Username: username, PasswordHash: pw, CreatedAt: now()}
	user := store.User{ID: newID("usr_"), AccountID: acc.ID, Kind: "admin", Email: email, DisplayName: "admin", PasswordHash: pw, Metadata: []byte("{}"), CreatedAt: now()}
	if err := s.DB.CreateAccount(c.Request.Context(), acc, user); err != nil {
		fail(c, 500, err.Error())
		return
	}
	_ = s.DB.PutKV(c.Request.Context(), "bootstrap.used", "1", now())
	s.setSession(c, user)
	_, _ = s.DB.AddEvent(c.Request.Context(), store.Event{AccountID: acc.ID, TS: now(), ActorRole: "admin", Actor: email, Action: "bootstrap"})
	c.JSON(http.StatusOK, gin.H{"ok": true, "admin_bootstrapped": true, "user": publicUser(user)})
}

func (s *Server) signup(c *gin.Context) {
	var body struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	body.Username = strings.TrimSpace(body.Username)
	if len(body.Username) < 3 || len(body.Password) < 8 {
		fail(c, 422, "username and password are required")
		return
	}
	pw, err := hashPassword(body.Password)
	if err != nil {
		fail(c, 500, "could not hash password")
		return
	}
	acc := store.Account{ID: newID("acc_"), Username: body.Username, PasswordHash: pw, CreatedAt: now()}
	user := store.User{ID: newID("usr_"), AccountID: acc.ID, Kind: "admin", DisplayName: body.Username, PasswordHash: pw, Metadata: []byte("{}"), CreatedAt: now()}
	if err := s.DB.CreateAccount(c.Request.Context(), acc, user); err != nil {
		if errors.Is(err, store.ErrConflict) {
			fail(c, 409, "username already exists")
			return
		}
		fail(c, 500, err.Error())
		return
	}
	s.setSession(c, user)
	_, _ = s.DB.AddEvent(c.Request.Context(), store.Event{AccountID: acc.ID, TS: now(), ActorRole: "admin", Actor: body.Username, Action: "signup"})
	c.JSON(http.StatusOK, gin.H{"ok": true, "account": gin.H{"id": acc.ID, "username": acc.Username}, "user": publicUser(user)})
}

func publicUser(u store.User) gin.H {
	return gin.H{"id": u.ID, "account_id": u.AccountID, "kind": u.Kind, "track": u.Track, "email": u.Email, "display_name": u.DisplayName, "disabled_at": u.DisabledAt}
}

func (s *Server) login(c *gin.Context) {
	var body struct {
		Username string `json:"username"`
		Email    string `json:"email"`
		Password string `json:"password"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	ident := strings.TrimSpace(body.Username)
	if ident == "" {
		ident = strings.TrimSpace(body.Email)
	}
	if ident == "" {
		fail(c, 422, "username or email is required")
		return
	}
	acc, user, err := s.DB.AccountByUsername(c.Request.Context(), ident)
	if err != nil || !checkPassword(acc.PasswordHash, body.Password) {
		fail(c, 401, "invalid username or password")
		return
	}
	s.setSession(c, user)
	_, _ = s.DB.AddEvent(c.Request.Context(), store.Event{AccountID: acc.ID, TS: now(), ActorRole: "admin", Actor: user.DisplayName, Action: "login"})
	c.JSON(http.StatusOK, gin.H{"ok": true, "user": publicUser(user), "account": gin.H{"id": acc.ID, "username": acc.Username}})
}

func (s *Server) logout(c *gin.Context) {
	p := principalFrom(c)
	if raw, err := c.Cookie(cookieSession); err == nil {
		s.dropSession(c, raw)
	}
	if p.SessionID != "" {
		_ = s.DB.DeleteSession(c.Request.Context(), p.SessionID)
	}
	c.SetCookie(cookieSession, "", -1, "/", "", false, true)
	c.SetCookie(cookieCSRF, "", -1, "/", "", false, false)
	c.JSON(http.StatusOK, gin.H{"ok": true, "role": p.Role})
}

func (s *Server) me(c *gin.Context) {
	p := principalFrom(c)
	out := gin.H{
		"role": p.Role, "actor": p.Actor, "user_id": p.UserID, "track": p.Track, "kind": p.Kind,
		"auth": p.Auth, "compat": p.Auth == "compat_role", "account_id": p.AccountID,
	}
	for k, v := range capabilities(p.Role) {
		out[k] = v
	}
	if p.UserID != "" {
		if u, err := s.DB.User(c.Request.Context(), p.UserID); err == nil {
			out["user"] = publicUser(u)
		}
	}
	c.JSON(http.StatusOK, out)
}

func (s *Server) meta(c *gin.Context) {
	p := principalFrom(c)
	c.JSON(http.StatusOK, gin.H{
		"statuses": statuses, "apply_kinds": applyKinds, "roles": []string{"discovery", "apply", "outreach", "admin", "maintenance"},
		"tracks":       []string{"discovery", "application", "outreach", "maintenance"},
		"capabilities": capabilities(p.Role), "queue_kinds": queueKinds, "queue_lease_m": 15,
		"heartbeat_s": 10, "store": s.DB.Name(), "cache": s.Cache.Name(), "blob": s.Blobs.Name(),
		"rabbitmq":            false,
		"streams":             gin.H{"sse": "/api/stream", "websocket": "/ws"},
		"candidate_onboarded": s.onboarded(c, p.AccountID),
		"registry":            "/api/registry/skills",
	})
}

func (s *Server) invalidateJobs(c *gin.Context, accountID string) {
	_ = s.Cache.DeletePrefix(c.Request.Context(), "jobs:"+accountID+":")
}

var wsUpgrader = websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}

func (s *Server) socket(c *gin.Context) {
	conn, err := wsUpgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		return
	}
	defer conn.Close()
	p := principalFrom(c)
	id, ch := s.RT.Subscribe(p.AccountID)
	defer s.RT.Unsubscribe(id)
	_ = conn.WriteJSON(gin.H{"event": "hello", "data": gin.H{"account_id": p.AccountID, "user_id": p.UserID}})
	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			_, msg, err := conn.ReadMessage()
			if err != nil {
				return
			}
			var frame struct {
				Type   string `json:"type"`
				Status string `json:"status"`
				TaskID string `json:"task_id"`
			}
			if json.Unmarshal(msg, &frame) == nil && frame.Type == "heartbeat" && p.UserID != "" {
				status := frame.Status
				if status == "" {
					status = "active"
				}
				_ = s.DB.SavePresence(c.Request.Context(), store.Presence{
					AccountID: p.AccountID, UserID: p.UserID, Status: status, TaskID: frame.TaskID, LastBeat: now(),
				})
				s.RT.Publish(p.AccountID, "presence", gin.H{"user_id": p.UserID, "status": status})
			}
		}
	}()
	for {
		select {
		case <-done:
			return
		case msg, ok := <-ch:
			if !ok {
				return
			}
			if err := conn.WriteMessage(websocket.TextMessage, msg); err != nil {
				return
			}
		}
	}
}

func (s *Server) stream(c *gin.Context) {
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	p := principalFrom(c)
	id, ch := s.RT.Subscribe(p.AccountID)
	defer s.RT.Unsubscribe(id)
	_, _ = c.Writer.Write([]byte(": connected\n\n"))
	c.Writer.Flush()
	c.Stream(func(w io.Writer) bool {
		select {
		case <-c.Request.Context().Done():
			return false
		case msg, ok := <-ch:
			if !ok {
				return false
			}
			_, _ = w.Write([]byte("data: "))
			_, _ = w.Write(msg)
			_, _ = w.Write([]byte("\n\n"))
			return true
		}
	})
}
