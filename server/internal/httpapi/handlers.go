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
	s.RT.Publish(p.AccountID, "job", gin.H{"action": "create", "id": j.ID})
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
	s.RT.Publish(p.AccountID, "job", gin.H{"action": "patch", "id": next.ID, "status": next.Status})
	c.JSON(http.StatusOK, gin.H{"job": next, "role": p.Role})
}

func (s *Server) syncQueue(c *gin.Context, p principal, j store.Job) {
	if j.Stopped {
		return
	}
	if j.Status == "apply_ready" && packetComplete(j.ApplyPacket) {
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
	s.RT.Publish(p.AccountID, "queue", gin.H{"action": "push", "id": item.ID, "kind": kind})
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
	s.RT.Publish(p.AccountID, "job", gin.H{"action": "delete", "id": c.Param("id")})
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
	case "application", "apply", "applicator":
		return "application"
	case "outreach":
		return "outreach"
	case "maintenance", "maintainer", "mainainer":
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
		c.JSON(409, gin.H{"detail": candidateRequiredBody()})
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
	s.bumpUser(c.Request.Context(), user.ID)
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
	if p.Role != "admin" && p.Track != user.Track {
		fail(c, 403, "owners can disable users on their own track")
		return
	}
	user.DisabledAt = now()
	_ = s.DB.SaveUser(c.Request.Context(), user)
	_ = s.DB.RevokeUserKeys(c.Request.Context(), user.ID, now())
	s.bumpUser(c.Request.Context(), user.ID)
	c.JSON(http.StatusOK, gin.H{"user": publicUser(user)})
}

func (s *Server) candidatePublic(c *gin.Context) {
	account := c.Query("account_id")
	if account == "" {
		if p, err := s.authenticate(c); err == nil {
			account = p.AccountID
		}
	}
	if account == "" {
		if admin, err := s.DB.FirstAdmin(c.Request.Context()); err == nil {
			account = admin.AccountID
		}
	}
	c.JSON(http.StatusOK, s.candidateState(c, account))
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
	if !realCandidate(string(body)) {
		fail(c, 422, "profile must name a real candidate")
		return
	}
	if err := s.Blobs.Put(c.Request.Context(), p.AccountID, candidateKey, body, "text/yaml", "candidate.yaml"); err != nil {
		fail(c, 500, err.Error())
		return
	}
	_ = s.Cache.DeletePrefix(c.Request.Context(), "cand:"+p.AccountID)
	c.JSON(http.StatusOK, gin.H{"ok": true, "onboarded": s.onboarded(c, p.AccountID)})
}

func (s *Server) getResume(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "apply" && p.Role != "outreach" && p.Role != "admin" {
		fail(c, 403, "only apply, outreach, or admin can download the resume PDF")
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
	if systemQueueKind(body.Kind) && p.Role != "admin" {
		fail(c, 403, "apply.ready and outreach.ready are system-enqueued on job status")
		return
	}
	if !contains(produceKinds(p.Role), body.Kind) {
		fail(c, 403, "this track cannot push "+body.Kind)
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
	s.RT.Publish(p.AccountID, "queue", gin.H{"action": "push", "id": item.ID, "kind": item.Kind})
	c.JSON(http.StatusOK, gin.H{"item": item})
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
	s.RT.Publish(p.AccountID, "queue", gin.H{"action": "claim", "count": len(claimed)})
	jobID, company := "", ""
	if len(claimed) > 0 {
		jobID = claimed[0].JobID
		if job, err := s.DB.Job(c.Request.Context(), p.AccountID, jobID); err == nil {
			company = job.Company
		}
	}
	c.JSON(http.StatusOK, gin.H{"items": claimed, "count": len(claimed), "memory": s.compactRecall(c, p, jobID, company)})
}

func (s *Server) compactRecall(c *gin.Context, p principal, jobID, company string) gin.H {
	key := "recall:" + p.AccountID + ":" + p.UserID + ":" + jobID + ":" + company
	if raw, ok, err := s.Cache.Get(c.Request.Context(), key); err == nil && ok {
		var hit gin.H
		if json.Unmarshal(raw, &hit) == nil {
			return hit
		}
	}
	items := s.recallMemory(c, p, "", "", jobID, company, "", 6, true)
	buckets := map[string][]store.MemoryItem{
		"worker": {},
		"track":  {},
		"common": {},
	}
	for _, item := range items {
		scope := podScope(item.Pod)
		buckets[scope] = append(buckets[scope], item)
	}
	nullIfEmpty := func(v string) any {
		if v == "" {
			return nil
		}
		return v
	}
	pods := []string{"common"}
	if p.UserID != "" {
		pods = append([]string{"worker:" + p.UserID}, pods...)
	}
	if p.Track != "" {
		pods = append(pods, "track:"+p.Track)
	}
	card := gin.H{
		"recall_url": "/api/memory/recall", "write_url": "/api/memory/items",
		"move_url": "/api/memory/items/{id}/move", "solidify_url": "/api/memory/items/{id}/solidify",
		"hint":    "Use these facts this round. Store only if another bot would need them tomorrow. Solidify track/common facts that should become skills.",
		"pods":    pods,
		"items":   items,
		"by_pod":  buckets,
		"counts":  gin.H{"worker": len(buckets["worker"]), "track": len(buckets["track"]), "common": len(buckets["common"])},
		"query":   nil,
		"job_id":  nullIfEmpty(jobID),
		"company": nullIfEmpty(company),
		"compact": true,
		"write_policy": gin.H{
			"window_s": 15 * 60,
			"caps":     gin.H{"worker": 6, "track": 3, "common": 2},
		},
	}
	if body, err := json.Marshal(card); err == nil {
		_ = s.Cache.Set(c.Request.Context(), key, body, recallCacheTTL)
	}
	return card
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
	if !s.queueClaimOwned(c, p, item) {
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

func packetComplete(raw json.RawMessage) bool {
	var packet map[string]any
	if len(raw) == 0 || json.Unmarshal(raw, &packet) != nil {
		return false
	}
	if url, _ := packet["url"].(string); strings.TrimSpace(url) != "" {
		return true
	}
	steps, _ := packet["steps"].([]any)
	return len(steps) > 0
}

func (s *Server) queueClaimOwned(c *gin.Context, p principal, item store.QueueItem) bool {
	if item.Status != "claimed" {
		fail(c, 409, "queue item is not claimed")
		return false
	}
	who := p.UserID
	if who == "" {
		who = p.Actor
	}
	if item.ClaimedBy != who && p.Role != "admin" {
		fail(c, 403, "only the claimant can change this queue item")
		return false
	}
	if p.Role != "admin" && item.LeaseUntil != "" && item.LeaseUntil < now() {
		fail(c, 409, "lease expired")
		return false
	}
	return true
}

func (s *Server) finishQueue(c *gin.Context, status string) {
	p := principalFrom(c)
	item, err := s.DB.QueueByID(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil {
		fail(c, 404, "queue item not found")
		return
	}
	if !s.queueClaimOwned(c, p, item) {
		return
	}
	item.Status = status
	item.LeaseUntil = ""
	_ = s.DB.SaveQueue(c.Request.Context(), item)
	s.RT.Publish(p.AccountID, "queue", gin.H{"action": status, "id": item.ID})
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
	if p.Role != "outreach" && p.Role != "admin" {
		fail(c, 403, "only outreach or admin can read people")
		return
	}
	person, err := s.DB.Person(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil {
		fail(c, 404, "person not found")
		return
	}
	c.JSON(http.StatusOK, gin.H{"person": person})
}

func (s *Server) patchPerson(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "outreach" && p.Role != "admin" {
		fail(c, 403, "only outreach or admin can write people")
		return
	}
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
	p := principalFrom(c)
	pods := []string{"worker:" + p.UserID}
	if p.Role == "admin" || p.Role == "maintenance" {
		for _, track := range hubTracks {
			pods = append(pods, "track:"+track)
		}
	} else if p.Track != "" {
		pods = append(pods, "track:"+p.Track)
	}
	pods = append(pods, "common")
	c.JSON(http.StatusOK, gin.H{
		"pods": pods,
		"write_policy": gin.H{
			"window_s": 15 * 60,
			"caps":     gin.H{"worker": 6, "track": 3, "common": 2},
		},
		"kinds": memoryKinds,
	})
}

func (s *Server) memoryRecall(c *gin.Context) {
	p := principalFrom(c)
	limit := queryLimit(c, 12, 24)
	compact := c.Query("compact") == "1" || c.Query("compact") == "true"
	kept := s.recallMemory(c, p, "", c.Query("q"), c.Query("job_id"), c.Query("company"), "", limit, compact)
	c.JSON(http.StatusOK, gin.H{"items": kept, "count": len(kept)})
}

func (s *Server) listMemory(c *gin.Context) {
	p := principalFrom(c)
	pod, msg := "", ""
	if raw := c.Query("pod"); raw != "" {
		pod, msg = resolveWritePod(p, raw)
		if msg != "" && p.Role != "admin" && p.Role != "maintenance" {
			fail(c, 403, msg)
			return
		}
		if msg != "" {
			pod = raw
		}
	}
	limit := queryLimit(c, 12, 100)
	kept := s.recallMemory(c, p, pod, c.Query("q"), c.Query("job_id"), c.Query("company"), c.Query("kind"), limit, false)
	c.JSON(http.StatusOK, gin.H{"items": kept, "count": len(kept)})
}

func (s *Server) recallMemory(c *gin.Context, p principal, pod, q, jobID, company, kind string, limit int, compact bool) []store.MemoryItem {
	if searcher, ok := s.DB.(interface {
		SearchMemory(ctx context.Context, q store.MemoryQuery) ([]store.MemoryItem, error)
	}); ok {
		query := store.MemoryQuery{
			AccountID: p.AccountID, Pod: pod, Kind: kind, JobID: jobID, Company: company, Q: q, Now: now(), Limit: limit,
		}
		if pod == "" && p.Role != "admin" && p.Role != "maintenance" {
			query.Pods = []string{"common", "worker:" + p.UserID}
			if p.Track != "" {
				query.Pods = append(query.Pods, "track:"+p.Track)
			}
		}
		items, err := searcher.SearchMemory(c.Request.Context(), query)
		if err == nil {
			if compact {
				for i := range items {
					items[i].Body = compactBody(items[i].Body)
				}
			}
			if items == nil {
				items = []store.MemoryItem{}
			}
			return items
		}
	}
	items := s.visibleMemory(c, p, pod)
	return filterMemory(items, q, jobID, company, kind, limit, compact)
}

func (s *Server) visibleMemory(c *gin.Context, p principal, pod string) []store.MemoryItem {
	items, err := s.DB.ListMemory(c.Request.Context(), p.AccountID, pod)
	if err != nil {
		return nil
	}
	var out []store.MemoryItem
	nowAt := time.Now().UTC()
	for _, item := range items {
		if !canReadPod(p, item.Pod) || memoryExpired(item, nowAt) {
			continue
		}
		out = append(out, item)
	}
	return out
}

func filterMemory(items []store.MemoryItem, q, jobID, company, kind string, limit int, compact bool) []store.MemoryItem {
	var kept []store.MemoryItem
	for _, item := range items {
		if !memoryMatches(item, q, jobID, company, kind) {
			continue
		}
		if compact {
			item.Body = compactBody(item.Body)
		}
		kept = append(kept, item)
		if len(kept) >= limit {
			break
		}
	}
	if kept == nil {
		kept = []store.MemoryItem{}
	}
	return kept
}

func queryLimit(c *gin.Context, fallback, max int) int {
	n, err := strconv.Atoi(c.Query("limit"))
	if err != nil || n < 1 {
		return fallback
	}
	if n > max {
		return max
	}
	return n
}

func (s *Server) createMemory(c *gin.Context) {
	p := principalFrom(c)
	var body struct {
		Pod        string `json:"pod"`
		Kind       string `json:"kind"`
		Title      string `json:"title"`
		Body       string `json:"body"`
		JobID      string `json:"job_id"`
		Company    string `json:"company"`
		Importance int    `json:"importance"`
		Pinned     bool   `json:"pinned"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	pod, msg := resolveWritePod(p, body.Pod)
	if msg != "" {
		status := 422
		if strings.Contains(msg, "cannot") {
			status = 403
		}
		fail(c, status, msg)
		return
	}
	if body.Kind == "" || body.Body == "" {
		fail(c, 422, "kind and body are required")
		return
	}
	body.Kind = strings.ToLower(strings.TrimSpace(body.Kind))
	body.Title = strings.Join(strings.Fields(body.Title), " ")
	if errText := validateMemory(pod, body.Kind, body.Title, body.Body); errText != "" {
		fail(c, 422, errText)
		return
	}
	importance := body.Importance
	if importance == 0 {
		importance = 2
	}
	if importance < 1 || importance > 3 {
		fail(c, 422, "importance must be 1, 2, or 3")
		return
	}
	existing, _ := s.DB.ListMemory(c.Request.Context(), p.AccountID, pod)
	digest := hash(strings.ToLower(body.Kind + "\n" + body.Title + "\n" + body.Body + "\n" + body.Company + "\n" + body.JobID))
	for _, item := range existing {
		if item.ContentHash == digest {
			c.JSON(http.StatusOK, gin.H{"item": item, "status": "exists"})
			return
		}
	}
	if memoryOverCap(existing, pod) {
		fail(c, 429, "memory write cap reached for this pod")
		return
	}
	item := store.MemoryItem{
		ID: newID("mem_"), AccountID: p.AccountID, Pod: pod, Kind: body.Kind, Title: body.Title, Body: strings.TrimSpace(body.Body),
		JobID: body.JobID, Company: body.Company, ContentHash: digest, Importance: strconv.Itoa(importance),
		ExpiresAt: defaultExpiry(pod, body.Kind, strconv.Itoa(importance)), Pinned: body.Pinned, Tags: []byte("[]"),
		SolidifyStatus: "none", CreatedBy: p.UserID, CreatedAt: now(), UpdatedAt: now(),
	}
	if err := s.DB.SaveMemory(c.Request.Context(), item); err != nil {
		fail(c, 500, err.Error())
		return
	}
	s.invalidateRecall(c, p.AccountID)
	c.JSON(http.StatusCreated, gin.H{"item": item, "status": "stored"})
}

func (s *Server) patchMemory(c *gin.Context) {
	p := principalFrom(c)
	item, err := s.DB.Memory(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil || !canReadPod(p, item.Pod) {
		fail(c, 404, "memory item not found")
		return
	}
	var body struct {
		Title string `json:"title"`
		Body  string `json:"body"`
		Kind  string `json:"kind"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	if body.Title != "" {
		item.Title = strings.Join(strings.Fields(body.Title), " ")
	}
	if body.Body != "" {
		item.Body = strings.TrimSpace(body.Body)
	}
	if body.Kind != "" {
		item.Kind = strings.ToLower(strings.TrimSpace(body.Kind))
	}
	if errText := validateMemory(item.Pod, item.Kind, item.Title, item.Body); errText != "" {
		fail(c, 422, errText)
		return
	}
	item.UpdatedAt = now()
	_ = s.DB.SaveMemory(c.Request.Context(), item)
	s.invalidateRecall(c, p.AccountID)
	c.JSON(http.StatusOK, gin.H{"item": item})
}

func (s *Server) deleteMemory(c *gin.Context) {
	p := principalFrom(c)
	item, err := s.DB.Memory(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil || !canReadPod(p, item.Pod) {
		fail(c, 404, "memory item not found")
		return
	}
	if err := s.DB.DeleteMemory(c.Request.Context(), p.AccountID, c.Param("id")); err != nil {
		fail(c, 404, "memory item not found")
		return
	}
	s.invalidateRecall(c, p.AccountID)
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (s *Server) moveMemory(c *gin.Context) {
	p := principalFrom(c)
	item, err := s.DB.Memory(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil || !canReadPod(p, item.Pod) {
		fail(c, 404, "memory item not found")
		return
	}
	var body struct {
		Pod          string `json:"pod"`
		Kind         string `json:"kind"`
		KeepOriginal bool   `json:"keep_original"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	pod, msg := resolveWritePod(p, body.Pod)
	if msg != "" {
		fail(c, 422, msg)
		return
	}
	kind := item.Kind
	if body.Kind != "" {
		kind = strings.ToLower(body.Kind)
	}
	if errText := validateMemory(pod, kind, item.Title, item.Body); errText != "" {
		fail(c, 422, errText)
		return
	}
	moved := item
	moved.Pod = pod
	moved.Kind = kind
	moved.UpdatedAt = now()
	moved.ExpiresAt = defaultExpiry(pod, kind, item.Importance)
	if body.KeepOriginal {
		moved.ID = newID("mem_")
		moved.CreatedAt = now()
	}
	if err := s.DB.SaveMemory(c.Request.Context(), moved); err != nil {
		fail(c, 500, err.Error())
		return
	}
	action := "memory_move"
	if body.KeepOriginal {
		action = "memory_copy"
	}
	_, _ = s.DB.AddEvent(c.Request.Context(), store.Event{AccountID: p.AccountID, TS: now(), ActorRole: p.Role, Actor: p.Actor, Action: action, Note: pod})
	s.invalidateRecall(c, p.AccountID)
	c.JSON(http.StatusOK, gin.H{"item": moved, "copied": body.KeepOriginal})
}

func (s *Server) solidifyMemory(c *gin.Context) {
	p := principalFrom(c)
	item, err := s.DB.Memory(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil || !canReadPod(p, item.Pod) {
		fail(c, 404, "memory item not found")
		return
	}
	item.SolidifyStatus = "queued"
	item.UpdatedAt = now()
	_ = s.DB.SaveMemory(c.Request.Context(), item)
	rec := store.Recording{ID: newID("rec_"), AccountID: p.AccountID, SkillID: item.ID, SubmitterID: p.UserID, Origin: "memory", Body: item.Body, Status: "pending", CreatedAt: now()}
	_ = s.DB.SaveRecording(c.Request.Context(), rec)
	_ = s.DB.SaveQueue(c.Request.Context(), store.QueueItem{ID: newID("qi_"), AccountID: p.AccountID, Kind: "skill.record", Track: "maintenance", Payload: mustJSON(gin.H{"recording_id": rec.ID}), Status: "open", DedupeKey: "skill.record:" + rec.ID, CreatedAt: now()})
	s.invalidateRecall(c, p.AccountID)
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
	s.RT.Publish(p.AccountID, "message", gin.H{"id": msg.ID, "type": msg.Type})
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
	var visible []store.Message
	for _, msg := range rows {
		if canSeeMessage(p, msg) {
			visible = append(visible, msg)
		}
	}
	if visible == nil {
		visible = []store.Message{}
	}
	c.JSON(http.StatusOK, gin.H{"messages": visible})
}

func canSeeMessage(p principal, msg store.Message) bool {
	if p.Role == "admin" {
		return true
	}
	if p.UserID != "" && msg.ToUserID == p.UserID {
		return true
	}
	return p.Track != "" && msg.ToTrack == p.Track
}

func (s *Server) readMessage(c *gin.Context) {
	p := principalFrom(c)
	msg, err := s.DB.Message(c.Request.Context(), p.AccountID, c.Param("id"))
	if err != nil || !canSeeMessage(p, msg) {
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
		JobID  string `json:"job_id"`
	}
	_ = c.ShouldBindJSON(&body)
	if body.Status == "" {
		body.Status = "active"
	}
	pr := store.Presence{AccountID: p.AccountID, UserID: p.UserID, Status: body.Status, TaskID: body.TaskID, LastBeat: now(), UserAgent: c.GetHeader("User-Agent")}
	_ = s.DB.SavePresence(c.Request.Context(), pr)
	s.RT.Publish(p.AccountID, "presence", pr)
	c.JSON(http.StatusOK, gin.H{"ok": true, "presence": pr, "memory": s.compactRecall(c, p, body.JobID, "")})
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

func (s *Server) getPresence(c *gin.Context) {
	p := principalFrom(c)
	rows, err := s.DB.ListPresence(c.Request.Context(), p.AccountID)
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	for _, row := range rows {
		if row.UserID == c.Param("id") {
			c.JSON(http.StatusOK, gin.H{"presence": row})
			return
		}
	}
	fail(c, 404, "presence not found")
}

func (s *Server) listUsers(c *gin.Context) {
	p := principalFrom(c)
	rows, err := s.DB.ListUsers(c.Request.Context(), p.AccountID, c.Query("kind"), c.Query("track"))
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	var out []gin.H
	for _, user := range rows {
		out = append(out, publicUser(user))
	}
	if out == nil {
		out = []gin.H{}
	}
	c.JSON(http.StatusOK, gin.H{"users": out, "count": len(out)})
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
	var visible []store.Skill
	for _, sk := range skills {
		if canSeeSkill(p, sk) {
			visible = append(visible, sk)
		}
	}
	if visible == nil {
		visible = []store.Skill{}
	}
	c.JSON(http.StatusOK, gin.H{"skills": visible})
}

func canSeeSkill(p principal, sk store.Skill) bool {
	if p.Role == "admin" || p.Role == "maintenance" {
		return true
	}
	if sk.Scope == "shared" {
		return sk.Status == "approved"
	}
	return sk.OwnerID == p.UserID
}

func (s *Server) getSkill(c *gin.Context) {
	p := principalFrom(c)
	sk, err := s.DB.Skill(c.Request.Context(), c.Param("id"))
	if err != nil || !canSeeSkill(p, sk) {
		fail(c, 404, "skill not found")
		return
	}
	c.JSON(http.StatusOK, gin.H{"skill": sk})
}

func (s *Server) patchSkill(c *gin.Context) {
	p := principalFrom(c)
	sk, err := s.DB.Skill(c.Request.Context(), c.Param("id"))
	if err != nil {
		fail(c, 404, "skill not found")
		return
	}
	if sk.Scope == "shared" && p.Role != "admin" && p.Role != "maintenance" {
		fail(c, 403, "shared skills are maintainer-owned")
		return
	}
	if sk.Scope == "local" && sk.OwnerID != "" && sk.OwnerID != p.UserID && p.Role != "admin" {
		fail(c, 403, "not your skill")
		return
	}
	var body struct {
		Name   string          `json:"name"`
		Body   string          `json:"body"`
		Status string          `json:"status"`
		Tags   json.RawMessage `json:"tags"`
	}
	if err := c.BindJSON(&body); err != nil {
		return
	}
	if body.Name != "" {
		sk.Name = body.Name
	}
	if body.Body != "" {
		sk.Body = body.Body
	}
	if body.Status != "" {
		if body.Status == "approved" && p.Role != "admin" && p.Role != "maintenance" {
			fail(c, 403, "shared skills are published through proctor")
			return
		}
		sk.Status = body.Status
	}
	if len(body.Tags) > 0 {
		sk.Tags = body.Tags
	}
	sk.Version++
	sk.UpdatedAt = now()
	if err := s.DB.SaveSkill(c.Request.Context(), sk); err != nil {
		fail(c, 500, err.Error())
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
	body.Scope = "local"
	body.Status = "draft"
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
	if err != nil || !canSeeSkill(p, src) {
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

func (s *Server) getRecording(c *gin.Context) {
	p := principalFrom(c)
	rows, err := s.DB.ListRecordings(c.Request.Context(), p.AccountID, "")
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	for _, row := range rows {
		if row.ID == c.Param("id") {
			c.JSON(http.StatusOK, gin.H{"recording": row})
			return
		}
	}
	fail(c, 404, "recording not found")
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

func (s *Server) a2aDirectory(c *gin.Context) {
	p := principalFrom(c)
	base := s.publicURL(c)
	local := []gin.H{{
		"id": "hub", "name": "Job Hub", "card_url": base + "/.well-known/agent-card.json", "agent_url": base + "/a2a",
	}}
	for _, track := range hubTracks {
		local = append(local, gin.H{
			"id": "hub-" + track, "name": "Job Hub / " + track, "track": track,
			"card_url": base + "/a2a/" + track + "/agent-card.json", "agent_url": base + "/a2a/" + track,
		})
	}
	peers, err := s.DB.ListPeers(c.Request.Context(), p.AccountID)
	if err != nil {
		fail(c, 500, err.Error())
		return
	}
	if peers == nil {
		peers = []store.Peer{}
	}
	c.JSON(http.StatusOK, gin.H{"local": local, "peers": peers, "protocolVersion": "0.3.0"})
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
