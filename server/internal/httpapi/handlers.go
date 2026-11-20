package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/unownone/jobos/server/internal/store"
)

func (s *Server) listJobs(c *gin.Context) {
	p := principalFrom(c)
	f := store.JobFilter{AccountID: p.AccountID, Status: c.Query("status"), Q: c.Query("q"), Location: c.Query("location"), ApplyKind: c.Query("apply_kind"), Remote: c.Query("remote"), Company: c.Query("company")}
	if v := c.Query("stopped"); v != "" {
		b := v == "true" || v == "1"
		f.Stopped = &b
	}
	if v := c.Query("has_pay"); v != "" {
		b := v == "true" || v == "1"
		f.HasPay = &b
	}
	if v := c.Query("score_min"); v != "" {
		if n, err := strconv.ParseFloat(v, 64); err == nil {
			f.ScoreMin = &n
		}
	}
	if v := c.Query("score_max"); v != "" {
		if n, err := strconv.ParseFloat(v, 64); err == nil {
			f.ScoreMax = &n
		}
	}
	if lane := c.Query("lane"); lane != "" {
		switch lane {
		case "discovery":
			for k := range discoveryLane {
				f.Lane = append(f.Lane, k)
			}
		case "apply":
			for k := range applyLane {
				f.Lane = append(f.Lane, k)
			}
		case "outreach":
			for k := range outreachLane {
				f.Lane = append(f.Lane, k)
			}
		default:
			fail(c, 422, "unknown lane")
			return
		}
	}
	if f.Status != "" && !knownStatus(f.Status) {
		fail(c, 422, "unknown status")
		return
	}
	f.Limit, _ = strconv.Atoi(c.Query("limit"))
	f.Offset, _ = strconv.Atoi(c.Query("offset"))
	key := "jobs:" + p.AccountID + ":" + c.Request.URL.RawQuery
	if raw, ok, _ := s.Cache.Get(c.Request.Context(), key); ok {
		c.Data(http.StatusOK, "application/json", raw)
		return
	}
	jobs, matched, total, err := s.DB.ListJobs(c.Request.Context(), f)
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	if jobs == nil {
		jobs = []store.Job{}
	}
	s.attachClaims(c, p.AccountID, jobs)
	body, _ := json.Marshal(gin.H{"jobs": jobs, "count": len(jobs), "matched": matched, "total": total, "limit": f.Limit, "offset": f.Offset, "role": p.Role})
	_ = s.Cache.Set(c.Request.Context(), key, body, 15*time.Second)
	c.Data(http.StatusOK, "application/json", body)
}

func (s *Server) attachClaims(c *gin.Context, accountID string, jobs []store.Job) {
	items, _ := s.DB.ListQueue(c.Request.Context(), accountID, "", "claimed")
	byJob := map[string]store.QueueItem{}
	for _, item := range items {
		if item.JobID != "" {
			byJob[item.JobID] = item
		}
	}
	for i := range jobs {
		if item, ok := byJob[jobs[i].ID]; ok {
			cp := item
			jobs[i].Claim = &cp
		}
	}
}

func (s *Server) createJob(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "discovery" && p.Role != "admin" {
		fail(c, 403, "this role cannot create jobs")
		return
	}
	var body map[string]any
	if err := c.BindJSON(&body); err != nil {
		return
	}
	company, _ := body["company"].(string)
	title, _ := body["title"].(string)
	if strings.TrimSpace(company) == "" || strings.TrimSpace(title) == "" {
		fail(c, 422, "company and title are required")
		return
	}
	id, _ := body["id"].(string)
	if id == "" {
		id = slug(company, title)
	}
	if _, err := s.DB.Job(c.Request.Context(), p.AccountID, id); err == nil {
		fail(c, 409, "job id already exists: "+id)
		return
	}
	applyURL, _ := body["apply_url"].(string)
	location, _ := body["location"].(string)
	if dup, ok, _ := s.DB.FindDuplicate(c.Request.Context(), p.AccountID, applyURL, company, title, location); ok {
		c.JSON(409, gin.H{"detail": "duplicate job", "existing_id": dup.ID})
		return
	}
	status := str(body, "status")
	if status == "" {
		status = "discovered"
	}
	if !knownStatus(status) || !laneFor(p.Role)[status] && status != "rejected" {
		fail(c, 422, "status is outside this role's lane")
		return
	}
	j := jobFromMap(p.AccountID, id, body)
	j.Status = status
	j.CreatedAt, j.UpdatedAt = now(), now()
	j.CreatedByRole = p.Role
	if err := s.DB.SaveJob(c.Request.Context(), j); err != nil {
		fail(c, 500, err.Error())
		return
	}
	_, _ = s.DB.AddEvent(c.Request.Context(), store.Event{AccountID: p.AccountID, TS: now(), JobID: j.ID, ActorRole: p.Role, Actor: p.Actor, Action: "create", ToStatus: j.Status})
	s.syncQueue(c, p, j)
	s.invalidateJobs(c, p.AccountID)
	s.RT.Publish("job", gin.H{"action": "create", "id": j.ID})
	c.JSON(http.StatusCreated, gin.H{"job": j, "role": p.Role})
}

func jobFromMap(account, id string, body map[string]any) store.Job {
	j := store.Job{AccountID: account, ID: id, Company: str(body, "company"), Title: str(body, "title"), Location: str(body, "location"), Remote: str(body, "remote"), URL: str(body, "url"), ApplyURL: str(body, "apply_url"), ApplyKind: str(body, "apply_kind"), ATS: str(body, "ats"), ReqID: str(body, "req_id"), Notes: str(body, "notes"), Description: str(body, "description"), Expectations: str(body, "expectations"), Pay: str(body, "pay"), PostedAt: str(body, "posted_at"), StopReason: str(body, "stop_reason")}
	j.Sources = jsonField(body, "sources", "[]")
	j.Owners = jsonField(body, "owners", "{}")
	j.ApplyPacket = jsonField(body, "apply_packet", "{}")
	j.OutreachPacket = jsonField(body, "outreach_packet", "{}")
	j.Research = jsonField(body, "research", "{}")
	j.Proof = jsonField(body, "proof", "{}")
	j.Rejection = jsonField(body, "rejection", "{}")
	j.Conflicts = jsonField(body, "conflicts", "[]")
	if n, ok := body["score"].(float64); ok {
		j.Score = &n
	}
	if b, ok := body["stopped"].(bool); ok {
		j.Stopped = b
	}
	return j
}

func jsonField(body map[string]any, key, fallback string) json.RawMessage {
	v, ok := body[key]
	if !ok || v == nil {
		return json.RawMessage(fallback)
	}
	b, err := json.Marshal(v)
	if err != nil {
		return json.RawMessage(fallback)
	}
	return b
}

func str(body map[string]any, key string) string {
	v, _ := body[key].(string)
	return strings.TrimSpace(v)
}

func slug(parts ...string) string {
	raw := strings.ToLower(strings.Join(parts, "-"))
	var b strings.Builder
	prev := false
	for _, r := range raw {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') {
			b.WriteRune(r)
			prev = false
			continue
		}
		if !prev {
			b.WriteByte('-')
			prev = true
		}
	}
	out := strings.Trim(b.String(), "-")
	if out == "" {
		out = "job"
	}
	return out + "-" + random(3)
}

func (s *Server) getJob(c *gin.Context) {
	p := principalFrom(c)
	j, err := s.DB.Job(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil {
		fail(c, 404, "job not found")
		return
	}
	jobs := []store.Job{j}
	s.attachClaims(c, p.AccountID, jobs)
	c.JSON(http.StatusOK, gin.H{"job": jobs[0], "role": p.Role})
}

func (s *Server) patchJob(c *gin.Context) {
	p := principalFrom(c)
	if !canPatch(p.Role) {
		fail(c, 403, "this role cannot patch jobs")
		return
	}
	j, err := s.DB.Job(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil {
		fail(c, 404, "job not found")
		return
	}
	if j.Stopped && p.Role != "admin" {
		fail(c, 409, "job is stopped")
		return
	}
	var body map[string]any
	if err := c.BindJSON(&body); err != nil {
		return
	}
	allowed := fieldsFor(p.Role)
	for k := range body {
		if !allowed[k] {
			fail(c, 403, "field not writable by this role: "+k)
			return
		}
	}
	from := j.Status
	if st, ok := body["status"].(string); ok && st != "" {
		if !knownStatus(st) {
			fail(c, 422, "unknown status")
			return
		}
		if st == "rejected" {
			rej, _ := body["rejection"].(map[string]any)
			by, _ := rej["by"].(string)
			if by != "company" && by != "user" {
				fail(c, 422, "rejection.by must be company or user")
				return
			}
		} else if !laneFor(p.Role)[st] {
			fail(c, 422, "status is outside this role's lane")
			return
		}
		j.Status = st
	}
	merged := map[string]any{}
	base, _ := json.Marshal(j)
	_ = json.Unmarshal(base, &merged)
	for k, v := range body {
		merged[k] = v
	}
	next := jobFromMap(j.AccountID, j.ID, merged)
	next.Status = j.Status
	next.CreatedAt = j.CreatedAt
	next.CreatedByRole = j.CreatedByRole
	next.UpdatedAt = now()
	next.Stopped = j.Stopped
	if b, ok := body["stopped"].(bool); ok && p.Role == "admin" {
		next.Stopped = b
	}
	if err := s.DB.SaveJob(c.Request.Context(), next); err != nil {
		fail(c, 500, err.Error())
		return
	}
	_, _ = s.DB.AddEvent(c.Request.Context(), store.Event{AccountID: p.AccountID, TS: now(), JobID: j.ID, ActorRole: p.Role, Actor: p.Actor, Action: "patch", FromStatus: from, ToStatus: next.Status, Fields: mustJSON(body)})
	s.syncQueue(c, p, next)
	s.invalidateJobs(c, p.AccountID)
	s.RT.Publish("job", gin.H{"action": "patch", "id": next.ID, "status": next.Status})
	c.JSON(http.StatusOK, gin.H{"job": next, "role": p.Role})
}

func (s *Server) syncQueue(c *gin.Context, p principal, j store.Job) {
	if j.Stopped {
		return
	}
	if j.Status == "apply_ready" {
		s.upsertQueue(c, p, "apply.ready", j.ID)
	}
	kind := strings.ToLower(j.ApplyKind)
	if j.Status == "applied" || ((kind == "network" || kind == "outreach_only") && j.Status == "outreach_ready") {
		s.upsertQueue(c, p, "outreach.ready", j.ID)
	}
}

func (s *Server) upsertQueue(c *gin.Context, p principal, kind, jobID string) {
	key := kind + ":" + jobID
	if _, ok, _ := s.DB.QueueByDedupe(c.Request.Context(), p.AccountID, key); ok {
		return
	}
	item := store.QueueItem{
		ID: newID("qi_"), AccountID: p.AccountID, Kind: kind, Track: kindTrack[kind], JobID: jobID,
		Payload: mustJSON(gin.H{"job_id": jobID}), Status: "open", DedupeKey: key, CreatedAt: now(),
	}
	_ = s.DB.SaveQueue(c.Request.Context(), item)
	s.RT.Publish("queue", gin.H{"action": "push", "id": item.ID, "kind": kind})
}

func (s *Server) deleteJob(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" {
		fail(c, 403, "only admin can delete a job")
		return
	}
	if err := s.DB.DeleteJob(c.Request.Context(), p.AccountID, c.Param("id")); err != nil {
		fail(c, 404, "job not found")
		return
	}
	s.invalidateJobs(c, p.AccountID)
	s.RT.Publish("job", gin.H{"action": "delete", "id": c.Param("id")})
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (s *Server) stopJob(c *gin.Context) {
	s.setStopped(c, true)
}

func (s *Server) pauseJob(c *gin.Context) { s.setStopped(c, true) }

func (s *Server) resumeJob(c *gin.Context) { s.setStopped(c, false) }

func (s *Server) setStopped(c *gin.Context, stopped bool) {
	p := principalFrom(c)
	if p.Role != "admin" {
		fail(c, 403, "only admin can stop a job")
		return
	}
	j, err := s.DB.Job(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil {
		fail(c, 404, "job not found")
		return
	}
	var body struct {
		Reason string `json:"reason"`
	}
	_ = c.ShouldBindJSON(&body)
	j.Stopped = stopped
	if body.Reason != "" {
		j.StopReason = body.Reason
	}
	j.UpdatedAt = now()
	_ = s.DB.SaveJob(c.Request.Context(), j)
	action := "resume"
	if stopped {
		action = "stop"
	}
	_, _ = s.DB.AddEvent(c.Request.Context(), store.Event{AccountID: p.AccountID, TS: now(), JobID: j.ID, ActorRole: p.Role, Actor: p.Actor, Action: action, Note: j.StopReason})
	s.invalidateJobs(c, p.AccountID)
	c.JSON(http.StatusOK, gin.H{"job": j})
}

func (s *Server) listEvents(c *gin.Context) {
	p := principalFrom(c)
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "50"))
	events, err := s.DB.ListEvents(c.Request.Context(), p.AccountID, c.Query("job_id"), limit)
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	if events == nil {
		events = []store.Event{}
	}
	c.JSON(http.StatusOK, gin.H{"events": events})
}

func (s *Server) hygiene(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" && p.Role != "maintenance" {
		fail(c, 403, "only admin or maintenance can run hygiene")
		return
	}
	counts, err := s.DB.CountByStatus(c.Request.Context(), p.AccountID)
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"counts": counts})
}

func (s *Server) vacuum(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" && p.Role != "maintenance" {
		fail(c, 403, "only admin or maintenance can run hygiene")
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true, "note": "autovacuum owns Postgres; the Go hub does not run VACUUM inside a request"})
}

func (s *Server) importJobs(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" && p.Role != "maintenance" {
		fail(c, 403, "only admin or maintenance can import history")
		return
	}
	var body struct {
		Jobs []map[string]any `json:"jobs"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	n := 0
	for _, raw := range body.Jobs {
		company, title := str(raw, "company"), str(raw, "title")
		if company == "" || title == "" {
			continue
		}
		id := str(raw, "id")
		if id == "" {
			id = slug(company, title)
		}
		j := jobFromMap(p.AccountID, id, raw)
		if j.Status == "" {
			j.Status = "discovered"
		}
		j.CreatedAt, j.UpdatedAt = now(), now()
		if err := s.DB.SaveJob(c.Request.Context(), j); err == nil {
			n++
		}
	}
	s.invalidateJobs(c, p.AccountID)
	c.JSON(http.StatusOK, gin.H{"imported": n})
}

func (s *Server) exportLedger(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" && p.Role != "maintenance" {
		fail(c, 403, "only admin or maintenance can export the ledger")
		return
	}
	jobs, _, _, err := s.DB.ListJobs(c.Request.Context(), store.JobFilter{AccountID: p.AccountID})
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	events, _ := s.DB.ListEvents(c.Request.Context(), p.AccountID, "", 500)
	c.JSON(http.StatusOK, gin.H{"jobs": jobs, "events": events})
}

func (s *Server) dashboard(c *gin.Context) {
	p := principalFrom(c)
	counts, err := s.DB.CountByStatus(c.Request.Context(), p.AccountID)
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"counts": counts, "candidate_onboarded": s.onboarded(c, p.AccountID), "cache": s.Cache.Name(), "blob": s.Blobs.Name()})
}

func (s *Server) createInvite(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" {
		fail(c, 403, "admin only")
		return
	}
	var body struct {
		Track          string `json:"track"`
		Mode           string `json:"mode"`
		MaxRedemptions int    `json:"max_redemptions"`
		TTLHours       int    `json:"ttl_hours"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	track := canonicalTrack(body.Track)
	if track == "" {
		fail(c, 422, "unknown track")
		return
	}
	if body.Mode == "" {
		body.Mode = "owner_then_agents"
	}
	if body.MaxRedemptions <= 0 {
		body.MaxRedemptions = 5
	}
	if body.TTLHours <= 0 {
		body.TTLHours = 72
	}
	secret := random(12)
	inv := store.Invite{
		ID: newID("inv_"), AccountID: p.AccountID, Track: track, Mode: body.Mode, SecretHash: hash(secret),
		MaxRedemptions: body.MaxRedemptions, ExpiresAt: time.Now().UTC().Add(time.Duration(body.TTLHours) * time.Hour).Format(time.RFC3339),
		CreatedBy: p.UserID, CreatedAt: now(),
	}
	if err := s.DB.CreateInvite(c.Request.Context(), inv); err != nil {
		fail(c, 500, err.Error())
		return
	}
	url := s.publicURL(c) + "/join/" + inv.ID + "?s=" + secret
	c.JSON(http.StatusOK, gin.H{"invite": publicInvite(inv), "secret": secret, "join_url": url, "token": "jh_inv_" + inv.ID + "." + secret, "shown_once": true})
}

func canonicalTrack(v string) string {
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "discovery":
		return "discovery"
	case "application", "apply":
		return "application"
	case "outreach":
		return "outreach"
	case "maintenance", "maintainer":
		return "maintenance"
	default:
		return ""
	}
}

func publicInvite(inv store.Invite) gin.H {
	return gin.H{"id": inv.ID, "track": inv.Track, "mode": inv.Mode, "max_redemptions": inv.MaxRedemptions, "redemptions": inv.Redemptions, "expires_at": inv.ExpiresAt, "revoked_at": inv.RevokedAt}
}

func (s *Server) listInvites(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" {
		fail(c, 403, "admin only")
		return
	}
	rows, err := s.DB.ListInvites(c.Request.Context(), p.AccountID)
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	out := []gin.H{}
	for _, inv := range rows {
		out = append(out, publicInvite(inv))
	}
	c.JSON(http.StatusOK, gin.H{"invites": out})
}

func (s *Server) revokeInvite(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" {
		fail(c, 403, "admin only")
		return
	}
	inv, err := s.DB.Invite(c.Request.Context(), c.Param("id"))
	if err != nil || inv.AccountID != p.AccountID {
		fail(c, 404, "invite not found")
		return
	}
	inv.RevokedAt = now()
	_ = s.DB.SaveInvite(c.Request.Context(), inv)
	c.JSON(http.StatusOK, gin.H{"invite": publicInvite(inv)})
}

func (s *Server) joinPreview(c *gin.Context) {
	inv, secret, ok := s.loadInvite(c, c.Param("id"), c.Query("s"))
	if !ok {
		return
	}
	c.JSON(http.StatusOK, gin.H{"invite_id": inv.ID, "track": inv.Track, "mode": inv.Mode, "secret_ok": secret != ""})
}

func (s *Server) loadInvite(c *gin.Context, id, secret string) (store.Invite, string, bool) {
	if secret == "" {
		fail(c, 401, "missing invite secret")
		return store.Invite{}, "", false
	}
	inv, err := s.DB.Invite(c.Request.Context(), id)
	if err != nil {
		fail(c, 404, "invite not found")
		return store.Invite{}, "", false
	}
	if inv.SecretHash != hash(secret) {
		fail(c, 401, "invalid invite secret")
		return store.Invite{}, "", false
	}
	if inv.RevokedAt != "" || inv.ExpiresAt < now() || inv.Redemptions >= inv.MaxRedemptions {
		fail(c, 409, "invite is not redeemable")
		return store.Invite{}, "", false
	}
	return inv, secret, true
}

func (s *Server) join(c *gin.Context) {
	var body struct {
		InviteID    string         `json:"invite_id"`
		S           string         `json:"s"`
		Secret      string         `json:"secret"`
		Token       string         `json:"token"`
		DisplayName string         `json:"display_name"`
		Metadata    map[string]any `json:"metadata"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	secret := body.S
	if secret == "" {
		secret = body.Secret
	}
	token := body.Token
	if token == "" {
		if h := c.GetHeader("Authorization"); strings.HasPrefix(strings.ToLower(h), "bearer ") {
			token = strings.TrimSpace(h[7:])
		}
	}
	if strings.HasPrefix(token, "jh_inv_") {
		rest := strings.TrimPrefix(token, "jh_inv_")
		if i := strings.Index(rest, "."); i > 0 {
			if body.InviteID == "" {
				body.InviteID = rest[:i]
			}
			if secret == "" {
				secret = rest[i+1:]
			}
		}
	}
	inv, _, ok := s.loadInvite(c, body.InviteID, secret)
	if !ok {
		return
	}
	if !s.onboarded(c, inv.AccountID) {
		c.JSON(409, gin.H{"code": "candidate_required", "message": "Onboard the candidate profile before using the Hub. Do not invent one.", "onboarding_url": "/onboarding"})
		return
	}
	kind := "agent"
	if inv.Mode == "owner_only" || (inv.Mode == "owner_then_agents" && inv.Redemptions == 0) {
		kind = "owner"
	}
	if body.DisplayName == "" {
		fail(c, 422, "display_name is required")
		return
	}
	meta := mustJSON(body.Metadata)
	user := store.User{ID: newID("usr_"), AccountID: inv.AccountID, Kind: kind, Track: inv.Track, DisplayName: body.DisplayName, Metadata: meta, CreatedBy: inv.CreatedBy, CreatedAt: now()}
	if err := s.DB.CreateUser(c.Request.Context(), user); err != nil {
		fail(c, 500, err.Error())
		return
	}
	plain := "jh_agt_" + random(16)
	prefix := "jh_agt_"
	if kind == "owner" {
		plain = "jh_own_" + inv.Track + "_" + random(12)
		prefix = "jh_own_" + inv.Track + "_"
	}
	_ = s.DB.CreateAPIKey(c.Request.Context(), store.APIKey{ID: newID("key_"), AccountID: inv.AccountID, UserID: user.ID, Prefix: prefix, KeyHash: hash(plain), CreatedAt: now()})
	inv.Redemptions++
	_ = s.DB.SaveInvite(c.Request.Context(), inv)
	c.JSON(http.StatusOK, gin.H{"user": publicUser(user), "api_key": plain, "shown_once": true})
}

func (s *Server) listAgents(c *gin.Context) {
	p := principalFrom(c)
	if p.Kind != "admin" && p.Kind != "owner" && p.Role != "admin" {
		fail(c, 403, "owner or admin only")
		return
	}
	track := ""
	if p.Kind == "owner" {
		track = p.Track
	}
	users, err := s.DB.ListUsers(c.Request.Context(), p.AccountID, "", track)
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	out := []gin.H{}
	for _, u := range users {
		if u.Kind == "agent" || u.Kind == "owner" {
			out = append(out, publicUser(u))
		}
	}
	c.JSON(http.StatusOK, gin.H{"users": out})
}

func (s *Server) createAgent(c *gin.Context) {
	p := principalFrom(c)
	if p.Kind == "agent" || (p.Kind != "admin" && p.Kind != "owner" && p.Role != "admin") {
		fail(c, 403, "only a track owner or admin can mint agents")
		return
	}
	var body struct {
		DisplayName string `json:"display_name"`
		Track       string `json:"track"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	track := p.Track
	if p.Role == "admin" || p.Kind == "admin" {
		track = canonicalTrack(body.Track)
		if track == "" {
			track = p.Track
		}
	}
	if track == "" || body.DisplayName == "" {
		fail(c, 422, "display_name and track are required")
		return
	}
	user := store.User{ID: newID("usr_"), AccountID: p.AccountID, Kind: "agent", Track: track, DisplayName: body.DisplayName, Metadata: []byte("{}"), CreatedBy: p.UserID, CreatedAt: now()}
	if err := s.DB.CreateUser(c.Request.Context(), user); err != nil {
		fail(c, 500, err.Error())
		return
	}
	plain := "jh_agt_" + random(16)
	_ = s.DB.CreateAPIKey(c.Request.Context(), store.APIKey{ID: newID("key_"), AccountID: p.AccountID, UserID: user.ID, Prefix: "jh_agt_", KeyHash: hash(plain), CreatedAt: now()})
	c.JSON(http.StatusOK, gin.H{"user": publicUser(user), "api_key": plain, "shown_once": true})
}

func (s *Server) rotateKey(c *gin.Context) {
	p := principalFrom(c)
	user, err := s.DB.User(c.Request.Context(), c.Param("id"))
	if err != nil || user.AccountID != p.AccountID {
		fail(c, 404, "user not found")
		return
	}
	if p.Role != "admin" && p.UserID != user.ID && !(p.Kind == "owner" && p.Track == user.Track) {
		fail(c, 403, "cannot manage this user")
		return
	}
	_ = s.DB.RevokeUserKeys(c.Request.Context(), user.ID, now())
	plain := "jh_agt_" + random(16)
	prefix := "jh_agt_"
	if user.Kind == "owner" {
		plain = "jh_own_" + user.Track + "_" + random(12)
		prefix = "jh_own_" + user.Track + "_"
	}
	_ = s.DB.CreateAPIKey(c.Request.Context(), store.APIKey{ID: newID("key_"), AccountID: user.AccountID, UserID: user.ID, Prefix: prefix, KeyHash: hash(plain), CreatedAt: now()})
	c.JSON(http.StatusOK, gin.H{"user": publicUser(user), "api_key": plain, "shown_once": true})
}

func (s *Server) disableAgent(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" && p.Kind != "owner" {
		fail(c, 403, "owner or admin only")
		return
	}
	user, err := s.DB.User(c.Request.Context(), c.Param("id"))
	if err != nil || user.AccountID != p.AccountID {
		fail(c, 404, "user not found")
		return
	}
	if user.Kind == "admin" {
		fail(c, 403, "cannot disable admin")
		return
	}
	user.DisabledAt = now()
	_ = s.DB.SaveUser(c.Request.Context(), user)
	_ = s.DB.RevokeUserKeys(c.Request.Context(), user.ID, now())
	c.JSON(http.StatusOK, gin.H{"user": publicUser(user)})
}

func (s *Server) candidatePublic(c *gin.Context) {
	account := c.Query("account_id")
	if account == "" {
		if p, err := s.authenticate(c); err == nil {
			account = p.AccountID
		}
	}
	present := account != "" && s.onboarded(c, account)
	c.JSON(http.StatusOK, gin.H{"present": present, "onboarded": present})
}

func (s *Server) candidateStatus(c *gin.Context) { s.candidatePublic(c) }

func (s *Server) candidateTemplate(c *gin.Context) {
	c.Data(http.StatusOK, "text/yaml; charset=utf-8", []byte("name: Your Name\ntitles:\n  - Software Engineer\nlocations:\n  - Remote\n"))
}

func (s *Server) getCandidate(c *gin.Context) {
	p := principalFrom(c)
	obj, err := s.Blobs.Get(c.Request.Context(), p.AccountID, candidateKey)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"present": false})
		return
	}
	c.JSON(http.StatusOK, gin.H{"present": true, "yaml": string(obj.Content)})
}

func (s *Server) putCandidate(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" && p.Kind != "admin" {
		fail(c, 403, "admin only")
		return
	}
	body, err := io.ReadAll(c.Request.Body)
	if err != nil || len(body) == 0 {
		fail(c, 422, "candidate yaml is required")
		return
	}
	text := string(body)
	if strings.Contains(text, "Ada Example") || !strings.Contains(text, "name:") {
		fail(c, 422, "profile must name a real candidate")
		return
	}
	if err := s.Blobs.Put(c.Request.Context(), p.AccountID, candidateKey, body, "text/yaml", "candidate.yaml"); err != nil {
		fail(c, 500, err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true, "onboarded": s.onboarded(c, p.AccountID)})
}

func (s *Server) getResume(c *gin.Context) {
	p := principalFrom(c)
	if p.Role == "discovery" {
		fail(c, 403, "discovery cannot download the resume PDF")
		return
	}
	obj, err := s.Blobs.Get(c.Request.Context(), p.AccountID, resumeKey)
	if err != nil {
		fail(c, 404, "resume not found")
		return
	}
	c.Data(http.StatusOK, "application/pdf", obj.Content)
}

func (s *Server) putResume(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" {
		fail(c, 403, "admin only")
		return
	}
	body, err := io.ReadAll(io.LimitReader(c.Request.Body, 8<<20))
	if err != nil || len(body) < 5 {
		fail(c, 422, "resume bytes are required")
		return
	}
	if err := s.Blobs.Put(c.Request.Context(), p.AccountID, resumeKey, body, "application/pdf", resumeKey); err != nil {
		fail(c, 500, err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true, "bytes": len(body), "driver": s.Blobs.Name()})
}

func (s *Server) queuePush(c *gin.Context) {
	p := principalFrom(c)
	var body struct {
		Kind    string         `json:"kind"`
		JobID   string         `json:"job_id"`
		Payload map[string]any `json:"payload"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	if _, ok := kindTrack[body.Kind]; !ok && !contains(queueKinds, body.Kind) {
		fail(c, 422, "unknown queue kind")
		return
	}
	key := body.Kind + ":" + body.JobID
	if body.JobID == "" {
		key = body.Kind + ":" + random(4)
	}
	if existing, ok, _ := s.DB.QueueByDedupe(c.Request.Context(), p.AccountID, key); ok {
		c.JSON(http.StatusOK, gin.H{"item": existing, "deduped": true})
		return
	}
	item := store.QueueItem{ID: newID("qi_"), AccountID: p.AccountID, Kind: body.Kind, Track: kindTrack[body.Kind], JobID: body.JobID, Payload: mustJSON(body.Payload), Status: "open", DedupeKey: key, CreatedAt: now()}
	if err := s.DB.SaveQueue(c.Request.Context(), item); err != nil {
		fail(c, 500, err.Error())
		return
	}
	s.RT.Publish("queue", gin.H{"action": "push", "id": item.ID, "kind": item.Kind})
	c.JSON(http.StatusCreated, gin.H{"item": item})
}

func contains(list []string, v string) bool {
	for _, item := range list {
		if item == v {
			return true
		}
	}
	return false
}

func (s *Server) queueClaim(c *gin.Context) {
	p := principalFrom(c)
	var body struct {
		Kinds []string `json:"kinds"`
		Limit int      `json:"limit"`
	}
	_ = c.ShouldBindJSON(&body)
	allowed := consumeKinds(p.Role)
	if len(allowed) == 0 {
		fail(c, 403, "this principal cannot claim queue work")
		return
	}
	kinds := allowed
	if len(body.Kinds) > 0 {
		kinds = nil
		for _, k := range body.Kinds {
			if contains(allowed, k) {
				kinds = append(kinds, k)
			}
		}
		if len(kinds) == 0 {
			fail(c, 403, "track cannot claim those kinds")
			return
		}
	}
	limit := body.Limit
	if limit <= 0 {
		limit = 1
	}
	if limit > 8 {
		limit = 8
	}
	who := p.UserID
	if who == "" {
		who = p.Actor
	}
	var claimed []store.QueueItem
	lease := time.Now().UTC().Add(15 * time.Minute).Format(time.RFC3339)
	for i := 0; i < limit; i++ {
		item, ok, err := s.DB.ClaimQueue(c.Request.Context(), p.AccountID, who, kinds, now(), lease)
		if err != nil {
			fail(c, 500, err.Error())
			return
		}
		if !ok {
			break
		}
		claimed = append(claimed, item)
	}
	if claimed == nil {
		claimed = []store.QueueItem{}
	}
	s.RT.Publish("queue", gin.H{"action": "claim", "count": len(claimed)})
	c.JSON(http.StatusOK, gin.H{"items": claimed})
}

func (s *Server) queueAck(c *gin.Context) {
	s.finishQueue(c, "acked")
}

func (s *Server) queueNack(c *gin.Context) {
	p := principalFrom(c)
	item, err := s.DB.QueueByID(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil {
		fail(c, 404, "queue item not found")
		return
	}
	var body struct {
		Requeue *bool  `json:"requeue"`
		Note    string `json:"note"`
	}
	_ = c.ShouldBindJSON(&body)
	requeue := true
	if body.Requeue != nil {
		requeue = *body.Requeue
	}
	item.Attempts++
	if !requeue || item.Attempts >= 5 {
		item.Status = "dead"
	} else {
		item.Status = "open"
		item.ClaimedBy = ""
		item.LeaseUntil = ""
	}
	_ = s.DB.SaveQueue(c.Request.Context(), item)
	c.JSON(http.StatusOK, gin.H{"item": item, "note": body.Note})
}

func (s *Server) finishQueue(c *gin.Context, status string) {
	p := principalFrom(c)
	item, err := s.DB.QueueByID(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil {
		fail(c, 404, "queue item not found")
		return
	}
	item.Status = status
	item.LeaseUntil = ""
	_ = s.DB.SaveQueue(c.Request.Context(), item)
	s.RT.Publish("queue", gin.H{"action": status, "id": item.ID})
	c.JSON(http.StatusOK, gin.H{"item": item})
}

func (s *Server) queueMine(c *gin.Context) {
	p := principalFrom(c)
	who := p.UserID
	if who == "" {
		who = p.Actor
	}
	items, err := s.DB.ListQueue(c.Request.Context(), p.AccountID, who, "claimed")
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	if items == nil {
		items = []store.QueueItem{}
	}
	c.JSON(http.StatusOK, gin.H{"items": items})
}

func (s *Server) queueList(c *gin.Context) {
	p := principalFrom(c)
	items, err := s.DB.ListQueue(c.Request.Context(), p.AccountID, "", c.Query("status"))
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	if items == nil {
		items = []store.QueueItem{}
	}
	c.JSON(http.StatusOK, gin.H{"items": items})
}

func (s *Server) listPeople(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "outreach" && p.Role != "admin" {
		fail(c, 403, "only outreach or admin can read people")
		return
	}
	rows, err := s.DB.ListPeople(c.Request.Context(), p.AccountID, c.Query("company"), c.Query("job_id"))
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	if rows == nil {
		rows = []store.Person{}
	}
	c.JSON(http.StatusOK, gin.H{"people": rows})
}

func (s *Server) createPerson(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "outreach" && p.Role != "admin" {
		fail(c, 403, "only outreach or admin can write people")
		return
	}
	var body store.Person
	if err := c.BindJSON(&body); err != nil {
		return
	}
	if body.Name == "" {
		fail(c, 422, "name is required")
		return
	}
	body.ID = newID("per_")
	body.AccountID = p.AccountID
	body.CreatedAt, body.UpdatedAt = now(), now()
	if len(body.Touches) == 0 {
		body.Touches = []byte("[]")
	}
	if err := s.DB.SavePerson(c.Request.Context(), body); err != nil {
		fail(c, 500, err.Error())
		return
	}
	c.JSON(http.StatusCreated, gin.H{"person": body})
}

func (s *Server) getPerson(c *gin.Context) {
	p := principalFrom(c)
	person, err := s.DB.Person(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil {
		fail(c, 404, "person not found")
		return
	}
	c.JSON(http.StatusOK, gin.H{"person": person})
}

func (s *Server) patchPerson(c *gin.Context) {
	p := principalFrom(c)
	person, err := s.DB.Person(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil {
		fail(c, 404, "person not found")
		return
	}
	var body map[string]any
	if err := c.BindJSON(&body); err != nil {
		return
	}
	if v := str(body, "name"); v != "" {
		person.Name = v
	}
	if v := str(body, "email"); v != "" {
		person.Email = v
	}
	if v := str(body, "notes"); v != "" {
		person.Notes = v
	}
	if b, ok := body["do_not_contact"].(bool); ok {
		person.DoNotContact = b
	}
	person.UpdatedAt = now()
	_ = s.DB.SavePerson(c.Request.Context(), person)
	c.JSON(http.StatusOK, gin.H{"person": person})
}

func (s *Server) memoryPods(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"pods": []string{"worker", "track", "common"}})
}

func (s *Server) memoryRecall(c *gin.Context) {
	p := principalFrom(c)
	items, err := s.DB.ListMemory(c.Request.Context(), p.AccountID, "")
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	var kept []store.MemoryItem
	for _, item := range items {
		if item.Pod == "common" || strings.HasPrefix(item.Pod, "track:") || strings.HasPrefix(item.Pod, "worker:"+p.UserID) {
			kept = append(kept, item)
		}
	}
	if kept == nil {
		kept = []store.MemoryItem{}
	}
	c.JSON(http.StatusOK, gin.H{"items": kept})
}

func (s *Server) listMemory(c *gin.Context) {
	p := principalFrom(c)
	items, err := s.DB.ListMemory(c.Request.Context(), p.AccountID, c.Query("pod"))
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	if items == nil {
		items = []store.MemoryItem{}
	}
	c.JSON(http.StatusOK, gin.H{"items": items})
}

func (s *Server) createMemory(c *gin.Context) {
	p := principalFrom(c)
	var body struct {
		Pod  string `json:"pod"`
		Kind string `json:"kind"`
		Body string `json:"body"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	pod := body.Pod
	switch pod {
	case "worker":
		pod = "worker:" + p.UserID
	case "track":
		pod = "track:" + p.Track
	case "common":
	default:
		if pod == "" {
			fail(c, 422, "pod must be worker, track, or common")
			return
		}
	}
	if body.Body == "" || body.Kind == "" {
		fail(c, 422, "kind and body are required")
		return
	}
	if err := memoryAllowed(pod, body.Kind, body.Body); err != "" {
		fail(c, 422, err)
		return
	}
	existing, _ := s.DB.ListMemory(c.Request.Context(), p.AccountID, pod)
	if memoryOverCap(existing, pod) {
		fail(c, 429, "memory write cap reached for this pod")
		return
	}
	item := store.MemoryItem{ID: newID("mem_"), AccountID: p.AccountID, Pod: pod, Kind: body.Kind, Body: body.Body, ContentHash: hash(body.Body), SolidifyStatus: "none", CreatedBy: p.UserID, CreatedAt: now(), UpdatedAt: now()}
	if err := s.DB.SaveMemory(c.Request.Context(), item); err != nil {
		fail(c, 500, err.Error())
		return
	}
	c.JSON(http.StatusCreated, gin.H{"item": item})
}

func (s *Server) patchMemory(c *gin.Context) {
	p := principalFrom(c)
	item, err := s.DB.Memory(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil {
		fail(c, 404, "memory item not found")
		return
	}
	var body struct {
		Body string `json:"body"`
		Kind string `json:"kind"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	if body.Body != "" {
		item.Body = body.Body
	}
	if body.Kind != "" {
		item.Kind = body.Kind
	}
	item.UpdatedAt = now()
	_ = s.DB.SaveMemory(c.Request.Context(), item)
	c.JSON(http.StatusOK, gin.H{"item": item})
}

func (s *Server) deleteMemory(c *gin.Context) {
	p := principalFrom(c)
	if err := s.DB.DeleteMemory(c.Request.Context(), p.AccountID, c.Param("id")); err != nil {
		fail(c, 404, "memory item not found")
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (s *Server) solidifyMemory(c *gin.Context) {
	p := principalFrom(c)
	item, err := s.DB.Memory(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil {
		fail(c, 404, "memory item not found")
		return
	}
	item.SolidifyStatus = "queued"
	item.UpdatedAt = now()
	_ = s.DB.SaveMemory(c.Request.Context(), item)
	rec := store.Recording{ID: newID("rec_"), AccountID: p.AccountID, SkillID: item.ID, SubmitterID: p.UserID, Origin: "memory", Body: item.Body, Status: "pending", CreatedAt: now()}
	_ = s.DB.SaveRecording(c.Request.Context(), rec)
	_ = s.DB.SaveQueue(c.Request.Context(), store.QueueItem{ID: newID("qi_"), AccountID: p.AccountID, Kind: "skill.record", Track: "maintenance", Payload: mustJSON(gin.H{"recording_id": rec.ID}), Status: "open", DedupeKey: "skill.record:" + rec.ID, CreatedAt: now()})
	c.JSON(http.StatusOK, gin.H{"item": item, "recording": rec})
}

func (s *Server) createMessage(c *gin.Context) {
	p := principalFrom(c)
	var body struct {
		ToUserID string `json:"to_user_id"`
		ToTrack  string `json:"to_track"`
		JobID    string `json:"job_id"`
		Type     string `json:"type"`
		Body     string `json:"body"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	if body.Body == "" {
		fail(c, 422, "body is required")
		return
	}
	if body.Type == "" {
		body.Type = "note"
	}
	msg := store.Message{ID: newID("msg_"), AccountID: p.AccountID, FromUserID: p.UserID, ToUserID: body.ToUserID, ToTrack: body.ToTrack, JobID: body.JobID, Type: body.Type, Body: body.Body, CreatedAt: now()}
	if err := s.DB.SaveMessage(c.Request.Context(), msg); err != nil {
		fail(c, 500, err.Error())
		return
	}
	s.RT.Publish("message", gin.H{"id": msg.ID, "type": msg.Type})
	c.JSON(http.StatusCreated, gin.H{"message": msg})
}

func (s *Server) listMessages(c *gin.Context) {
	p := principalFrom(c)
	unread := c.Query("unread") == "1" || c.Query("unread") == "true"
	rows, err := s.DB.ListMessages(c.Request.Context(), p.AccountID, unread)
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	if rows == nil {
		rows = []store.Message{}
	}
	c.JSON(http.StatusOK, gin.H{"messages": rows})
}

func (s *Server) readMessage(c *gin.Context) {
	p := principalFrom(c)
	msg, err := s.DB.Message(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil {
		fail(c, 404, "message not found")
		return
	}
	msg.ReadAt = now()
	_ = s.DB.SaveMessage(c.Request.Context(), msg)
	c.JSON(http.StatusOK, gin.H{"message": msg})
}

func (s *Server) heartbeat(c *gin.Context) {
	p := principalFrom(c)
	if p.UserID == "" {
		c.JSON(http.StatusOK, gin.H{"ok": true, "compat": true})
		return
	}
	var body struct {
		Status string `json:"status"`
		TaskID string `json:"task_id"`
	}
	_ = c.ShouldBindJSON(&body)
	if body.Status == "" {
		body.Status = "active"
	}
	pr := store.Presence{AccountID: p.AccountID, UserID: p.UserID, Status: body.Status, TaskID: body.TaskID, LastBeat: now(), UserAgent: c.GetHeader("User-Agent")}
	_ = s.DB.SavePresence(c.Request.Context(), pr)
	s.RT.Publish("presence", pr)
	c.JSON(http.StatusOK, gin.H{"presence": pr})
}

func (s *Server) listPresence(c *gin.Context) {
	p := principalFrom(c)
	rows, err := s.DB.ListPresence(c.Request.Context(), p.AccountID)
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	if rows == nil {
		rows = []store.Presence{}
	}
	c.JSON(http.StatusOK, gin.H{"presence": rows})
}

func (s *Server) catalog(c *gin.Context) {
	skills, err := s.DB.ListSkills(c.Request.Context(), "shared", "shared", "approved", c.Query("tag"))
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	if skills == nil {
		skills = []store.Skill{}
	}
	c.JSON(http.StatusOK, gin.H{"skills": skills})
}

func (s *Server) listSkills(c *gin.Context) {
	p := principalFrom(c)
	skills, err := s.DB.ListSkills(c.Request.Context(), p.AccountID, c.Query("scope"), c.Query("status"), c.Query("tag"))
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	if skills == nil {
		skills = []store.Skill{}
	}
	c.JSON(http.StatusOK, gin.H{"skills": skills})
}

func (s *Server) getSkill(c *gin.Context) {
	sk, err := s.DB.Skill(c.Request.Context(), c.Param("id"))
	if err != nil {
		fail(c, 404, "skill not found")
		return
	}
	c.JSON(http.StatusOK, gin.H{"skill": sk})
}

func (s *Server) createSkill(c *gin.Context) {
	p := principalFrom(c)
	var body store.Skill
	if err := c.BindJSON(&body); err != nil {
		return
	}
	if body.Name == "" || body.Body == "" {
		fail(c, 422, "name and body are required")
		return
	}
	body.ID = newID("skl_")
	body.AccountID = p.AccountID
	if body.Scope == "" {
		body.Scope = "local"
	}
	if body.Status == "" {
		body.Status = "draft"
	}
	if body.Kind == "" {
		body.Kind = "skill"
	}
	if len(body.Tags) == 0 {
		body.Tags = []byte("[]")
	}
	body.OwnerID = p.UserID
	body.Origin = "recording"
	body.Version = 1
	body.CreatedAt, body.UpdatedAt = now(), now()
	if err := s.DB.SaveSkill(c.Request.Context(), body); err != nil {
		fail(c, 500, err.Error())
		return
	}
	c.JSON(http.StatusCreated, gin.H{"skill": body})
}

func (s *Server) forkSkill(c *gin.Context) {
	p := principalFrom(c)
	src, err := s.DB.Skill(c.Request.Context(), c.Param("id"))
	if err != nil {
		fail(c, 404, "skill not found")
		return
	}
	fork := src
	fork.ID = newID("skl_")
	fork.AccountID = p.AccountID
	fork.Scope = "local"
	fork.OwnerID = p.UserID
	fork.Status = "draft"
	fork.Origin = "mutation"
	fork.Version = src.Version + 1
	fork.CreatedAt, fork.UpdatedAt = now(), now()
	if err := s.DB.SaveSkill(c.Request.Context(), fork); err != nil {
		fail(c, 500, err.Error())
		return
	}
	c.JSON(http.StatusCreated, gin.H{"skill": fork})
}

func (s *Server) listMCPs(c *gin.Context) {
	p := principalFrom(c)
	rows, err := s.DB.ListMCPs(c.Request.Context(), p.AccountID)
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	status := c.Query("status")
	kind := c.Query("kind")
	var out []store.MCP
	for _, item := range rows {
		if status != "" && item.Status != status {
			continue
		}
		if kind != "" && item.Kind != kind {
			continue
		}
		out = append(out, item)
	}
	if out == nil {
		out = []store.MCP{}
	}
	c.JSON(http.StatusOK, gin.H{"mcps": out, "count": len(out)})
}

func (s *Server) getMCP(c *gin.Context) {
	p := principalFrom(c)
	item, err := s.DB.MCP(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil {
		fail(c, 404, "mcp not found")
		return
	}
	c.JSON(http.StatusOK, gin.H{"mcp": item})
}

func (s *Server) createRecording(c *gin.Context) {
	p := principalFrom(c)
	var body struct {
		SkillID string `json:"skill_id"`
		Body    string `json:"body"`
		Origin  string `json:"origin"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	rec := store.Recording{ID: newID("rec_"), AccountID: p.AccountID, SkillID: body.SkillID, SubmitterID: p.UserID, Origin: body.Origin, Body: body.Body, Status: "pending", CreatedAt: now()}
	if rec.Origin == "" {
		rec.Origin = "recording"
	}
	_ = s.DB.SaveRecording(c.Request.Context(), rec)
	_ = s.DB.SaveQueue(c.Request.Context(), store.QueueItem{ID: newID("qi_"), AccountID: p.AccountID, Kind: "skill.record", Track: "maintenance", Status: "open", DedupeKey: "skill.record:" + rec.ID, Payload: mustJSON(gin.H{"recording_id": rec.ID}), CreatedAt: now()})
	c.JSON(http.StatusCreated, gin.H{"recording": rec})
}

func (s *Server) listRecordings(c *gin.Context) {
	p := principalFrom(c)
	rows, err := s.DB.ListRecordings(c.Request.Context(), p.AccountID, c.Query("status"))
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	if rows == nil {
		rows = []store.Recording{}
	}
	c.JSON(http.StatusOK, gin.H{"recordings": rows})
}

func (s *Server) proctorRecording(c *gin.Context) {
	s.setRecording(c, "")
}

func (s *Server) promoteRecording(c *gin.Context) { s.setRecording(c, "promoted") }

func (s *Server) declineRecording(c *gin.Context) { s.setRecording(c, "declined") }

func (s *Server) setRecording(c *gin.Context, force string) {
	p := principalFrom(c)
	if p.Role != "admin" && p.Role != "maintenance" {
		fail(c, 403, "maintainer only")
		return
	}
	rec, err := s.DB.Recording(c.Request.Context(), c.Param("id"))
	if errors.Is(err, store.ErrNotFound) {
		fail(c, 404, "recording not found")
		return
	}
	var body struct {
		Status string `json:"status"`
		Note   string `json:"note"`
	}
	_ = c.ShouldBindJSON(&body)
	if force != "" {
		rec.Status = force
	} else if body.Status != "" {
		rec.Status = body.Status
	}
	rec.Note = body.Note
	_ = s.DB.SaveRecording(c.Request.Context(), rec)
	if rec.Status == "promoted" && rec.SkillID != "" {
		if sk, err := s.DB.Skill(c.Request.Context(), rec.SkillID); err == nil {
			sk.Status = "approved"
			sk.Scope = "shared"
			sk.UpdatedAt = now()
			_ = s.DB.SaveSkill(c.Request.Context(), sk)
		}
	}
	c.JSON(http.StatusOK, gin.H{"recording": rec})
}

func (s *Server) seedSkills(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" && p.Role != "maintenance" {
		fail(c, 403, "maintainer only")
		return
	}
	n := s.Seed(c.Request.Context())
	c.JSON(http.StatusOK, gin.H{"seeded": n})
}

func memoryAllowed(pod, kind, body string) string {
	podKind := pod
	switch {
	case strings.HasPrefix(pod, "worker:"):
		podKind = "worker"
	case strings.HasPrefix(pod, "track:"):
		podKind = "track"
	}
	allowed := map[string]map[string]bool{
		"worker": {"working_note": true, "reminder": true, "fact": true},
		"track": {
			"portal_quirk": true, "blocker": true, "tool_failure": true, "company_note": true,
			"process_note": true, "person_hint": true, "search_coverage": true,
		},
		"common": {
			"process_note": true, "tool_failure": true, "catalog_note": true,
			"candidate_constraint": true, "hub_note": true,
		},
	}
	if !allowed[podKind][kind] {
		return "kind is not allowed in this pod"
	}
	if len(body) > 800 {
		return "body is too long"
	}
	min := 40
	if kind == "working_note" || kind == "reminder" {
		min = 24
	}
	if len(strings.TrimSpace(body)) < min {
		return "body is too short"
	}
	lower := strings.ToLower(body)
	for _, prefix := range []string{"jh_agt_", "jh_own_", "jh_inv_", "jh_boot_"} {
		if strings.Contains(lower, prefix) {
			return "memory must not contain secrets"
		}
	}
	return ""
}

func memoryOverCap(items []store.MemoryItem, pod string) bool {
	capN := 6
	switch {
	case strings.HasPrefix(pod, "track:"):
		capN = 3
	case pod == "common":
		capN = 2
	}
	cutoff := time.Now().UTC().Add(-15 * time.Minute)
	n := 0
	for _, item := range items {
		stamp, err := time.Parse(time.RFC3339, item.CreatedAt)
		if err == nil && stamp.After(cutoff) {
			n++
		}
	}
	return n >= capN
}

func (s *Server) Seed(ctx context.Context) int {
	type row struct{ slug, name, role, tag, body string }
	rows := []row{
		{"job-discovery", "Job discovery", "discovery", "source", "Find and score jobs. Never Easy Apply."},
		{"job-apply", "Job apply", "apply", "apply", "Submit from the apply packet and log proof."},
		{"job-outreach", "Job outreach", "outreach", "outreach", "Email with the resume PDF and a short LinkedIn note."},
		{"deep-research", "Deep research", "research", "research", "Check the company and the hiring manager."},
		{"skill-maintainer", "Skill maintainer", "maintain", "maintain", "Proctor recordings and keep the registry."},
	}
	n := 0
	for _, row := range rows {
		id := "skl_" + row.slug
		if _, err := s.DB.Skill(ctx, id); err == nil {
			continue
		}
		sk := store.Skill{ID: id, AccountID: "shared", Slug: row.slug, Name: row.name, Kind: "skill", Role: row.role, Tags: mustJSON([]string{row.tag}), Scope: "shared", Status: "approved", Body: row.body, Origin: "github", Version: 1, CreatedAt: now(), UpdatedAt: now()}
		if err := s.DB.SaveSkill(ctx, sk); err == nil {
			n++
		}
	}
	n += s.seedMCPs(ctx)
	return n
}

func (s *Server) seedMCPs(ctx context.Context) int {
	type spec struct{ slug, kind, source string }
	var specs []spec
	if s.Cfg.RepoRoot != "" {
		raw, err := os.ReadFile(filepath.Join(s.Cfg.RepoRoot, "mcp", "mcp.example.json"))
		if err == nil {
			var doc struct {
				Servers map[string]struct {
					Type string `json:"type"`
					URL  string `json:"url"`
				} `json:"mcpServers"`
			}
			if json.Unmarshal(raw, &doc) == nil {
				for slug, cfg := range doc.Servers {
					kind := "mcp"
					if cfg.Type != "" {
						kind = cfg.Type
					}
					specs = append(specs, spec{slug: slug, kind: kind, source: cfg.URL})
				}
			}
		}
	}
	if len(specs) == 0 {
		specs = []spec{{slug: "gmail", kind: "http", source: "https://gmailmcp.googleapis.com/mcp/v1"}, {slug: "indeed", kind: "http", source: "https://mcp.indeed.com/claude/mcp"}}
	}
	n := 0
	for _, spec := range specs {
		id := "mcp_" + spec.slug
		if _, err := s.DB.MCP(ctx, "shared", id); err == nil {
			continue
		}
		item := store.MCP{
			AccountID: "shared", ID: id, Slug: spec.slug, Name: spec.slug, Kind: spec.kind, Status: "adopted",
			Capability: []byte("[]"), Roles: []byte("[]"), Platforms: []byte("[]"), Source: spec.source,
			Origin: "github", CreatedAt: now(), UpdatedAt: now(),
		}
		if err := s.DB.SaveMCP(ctx, item); err == nil {
			n++
		}
	}
	return n
}

func (s *Server) addBurn(c *gin.Context) {
	p := principalFrom(c)
	var b store.Burn
	if err := c.BindJSON(&b); err != nil {
		return
	}
	if b.ToolName == "" {
		fail(c, 422, "tool_name is required")
		return
	}
	b.AccountID = p.AccountID
	b.TS = now()
	b.ActorRole = p.Role
	b.Actor = p.Actor
	if b.TotalTokens == 0 {
		b.TotalTokens = b.PromptTokens + b.CompletionTokens
	}
	saved, err := s.DB.AddBurn(c.Request.Context(), b)
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	c.JSON(http.StatusCreated, gin.H{"burn": saved})
}

func (s *Server) listBurns(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" && p.Role != "maintenance" {
		fail(c, 403, "only admin or maintenance can read metrics")
		return
	}
	rows, err := s.DB.ListBurns(c.Request.Context(), p.AccountID, 100)
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	if rows == nil {
		rows = []store.Burn{}
	}
	c.JSON(http.StatusOK, gin.H{"burns": rows})
}

func (s *Server) burnSummary(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" && p.Role != "maintenance" {
		fail(c, 403, "only admin or maintenance can read metrics")
		return
	}
	rows, err := s.DB.ListBurns(c.Request.Context(), p.AccountID, 1000)
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	var prompt, completion int
	var cost float64
	for _, b := range rows {
		prompt += b.PromptTokens
		completion += b.CompletionTokens
		cost += b.CostUSD
	}
	c.JSON(http.StatusOK, gin.H{"count": len(rows), "prompt_tokens": prompt, "completion_tokens": completion, "cost_usd": cost})
}

func (s *Server) listPeers(c *gin.Context) {
	p := principalFrom(c)
	rows, err := s.DB.ListPeers(c.Request.Context(), p.AccountID)
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	if rows == nil {
		rows = []store.Peer{}
	}
	c.JSON(http.StatusOK, gin.H{"peers": rows})
}

func (s *Server) createPeer(c *gin.Context) {
	p := principalFrom(c)
	var body struct {
		Name string `json:"name"`
		URL  string `json:"url"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	if body.URL == "" {
		fail(c, 422, "url is required")
		return
	}
	peer := store.Peer{ID: newID("peer_"), AccountID: p.AccountID, Name: body.Name, URL: body.URL, CreatedAt: now()}
	if err := s.DB.SavePeer(c.Request.Context(), peer); err != nil {
		fail(c, 500, err.Error())
		return
	}
	c.JSON(http.StatusCreated, gin.H{"peer": peer})
}

func (s *Server) sendPeer(c *gin.Context) {
	p := principalFrom(c)
	var body map[string]any
	_ = c.ShouldBindJSON(&body)
	task := store.Task{ID: newID("task_"), AccountID: p.AccountID, State: "submitted", Payload: mustJSON(body), CreatedAt: now()}
	_ = s.DB.SaveTask(c.Request.Context(), task)
	c.JSON(http.StatusOK, gin.H{"task": task, "peer_id": c.Param("id")})
}

func (s *Server) a2a(c *gin.Context) {
	var body struct {
		JSONRPC string `json:"jsonrpc"`
		ID      any    `json:"id"`
		Method  string `json:"method"`
		Params  struct {
			Message struct {
				Parts []struct {
					Kind string `json:"kind"`
					Text string `json:"text"`
				} `json:"parts"`
			} `json:"message"`
		} `json:"params"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	account := "public"
	if p, err := s.authenticate(c); err == nil {
		account = p.AccountID
	}
	task := store.Task{ID: newID("task_"), AccountID: account, Track: c.Param("track"), State: "submitted", Payload: mustJSON(body), CreatedAt: now()}
	_ = s.DB.SaveTask(c.Request.Context(), task)
	text := ""
	for _, part := range body.Params.Message.Parts {
		if part.Kind == "text" {
			text = part.Text
		}
	}
	c.JSON(http.StatusOK, gin.H{
		"jsonrpc": "2.0",
		"id":      body.ID,
		"result": gin.H{
			"id": task.ID, "status": gin.H{"state": "submitted"},
			"history": []any{},
			"echo":    text,
		},
	})
}
