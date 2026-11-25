package httpapi

import (
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/unownone/jobos/server/internal/agentflow"
	"github.com/unownone/jobos/server/internal/store"
)

func (s *Server) toolWhoami(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	return gin.H{
		"account_id": p.AccountID, "user_id": p.UserID, "role": p.Role, "track": p.Track,
		"kind": p.Kind, "actor": p.Actor, "auth": "mcp",
	}, nil
}

func (s *Server) toolOnboarding(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	state := s.candidateState(c, grant.AccountID)
	return gin.H{
		"track": p.Track, "role": p.Role, "candidate": state,
		"hint": "Prefer MCP tools over HTTP. Read skills via read_skill / list_skills. Heartbeat via heartbeat.",
	}, nil
}

func (s *Server) toolGetCandidate(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	obj, err := s.Blobs.Get(c.Request.Context(), grant.AccountID, candidateKey)
	if err != nil {
		return gin.H{"present": false}, nil
	}
	return gin.H{"present": true, "yaml": string(obj.Content)}, nil
}

func (s *Server) toolDeleteJob(c *gin.Context, grant agentflow.Grant, id string) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" {
		return nil, errString("only admin can delete jobs")
	}
	if err := s.DB.DeleteJob(c.Request.Context(), grant.AccountID, id); err != nil {
		return nil, errString("job not found")
	}
	s.invalidateJobs(c, grant.AccountID)
	return gin.H{"ok": true, "id": id}, nil
}

func (s *Server) toolStopJob(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	return s.toolSetStopped(c, grant, strAny(args["id"]), true, strAny(args["reason"]))
}

func (s *Server) toolPauseResumeJob(c *gin.Context, grant agentflow.Grant, id string, stopped bool) (gin.H, error) {
	return s.toolSetStopped(c, grant, id, stopped, "")
}

func (s *Server) toolSetStopped(c *gin.Context, grant agentflow.Grant, id string, stopped bool, reason string) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" {
		return nil, errString("only admin can stop or resume a job")
	}
	job, err := s.DB.Job(c.Request.Context(), grant.AccountID, id)
	if err != nil {
		return nil, errString("job not found")
	}
	job.Stopped = stopped
	if reason != "" {
		job.StopReason = reason
	}
	job.UpdatedAt = now()
	if err := s.DB.SaveJob(c.Request.Context(), job); err != nil {
		return nil, err
	}
	action := "resume"
	if stopped {
		action = "stop"
	}
	_, _ = s.DB.AddEvent(c.Request.Context(), store.Event{
		AccountID: p.AccountID, TS: now(), JobID: job.ID, ActorRole: p.Role, Actor: p.Actor, Action: action, Note: job.StopReason,
	})
	s.invalidateJobs(c, grant.AccountID)
	return gin.H{"job": job}, nil
}

func (s *Server) toolQueuePush(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	kind := strAny(args["kind"])
	jobID := strAny(args["job_id"])
	if kind == "" {
		return nil, errString("kind is required")
	}
	if _, ok := kindTrack[kind]; !ok && !contains(queueKinds, kind) {
		return nil, errString("unknown queue kind")
	}
	if systemQueueKind(kind) && p.Role != "admin" {
		return nil, errString("apply.ready and outreach.ready are system-enqueued on job status")
	}
	if !contains(produceKinds(p.Role), kind) {
		return nil, errString("this track cannot push " + kind)
	}
	key := kind + ":" + jobID
	if jobID == "" {
		key = kind + ":" + random(4)
	}
	if existing, ok, _ := s.DB.QueueByDedupe(c.Request.Context(), p.AccountID, key); ok {
		return gin.H{"item": existing, "deduped": true}, nil
	}
	item := store.QueueItem{
		ID: newID("qi_"), AccountID: p.AccountID, Kind: kind, Track: kindTrack[kind], JobID: jobID,
		Payload: mustJSON(args["payload"]), Status: "open", DedupeKey: key, CreatedAt: now(),
	}
	if err := s.DB.SaveQueue(c.Request.Context(), item); err != nil {
		return nil, err
	}
	return gin.H{"item": item}, nil
}

func (s *Server) toolQueueClaim(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	allowed := consumeKinds(p.Role)
	if len(allowed) == 0 {
		return nil, errString("this principal cannot claim queue work")
	}
	kinds := allowed
	if raw, ok := args["kinds"].([]any); ok && len(raw) > 0 {
		kinds = nil
		for _, item := range raw {
			k := strAny(item)
			if contains(allowed, k) {
				kinds = append(kinds, k)
			}
		}
		if len(kinds) == 0 {
			return nil, errString("track cannot claim those kinds")
		}
	}
	limit := 1
	switch v := args["limit"].(type) {
	case float64:
		limit = int(v)
	case int:
		limit = v
	}
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
	lease := time.Now().UTC().Add(15 * time.Minute).Format(time.RFC3339)
	var claimed []store.QueueItem
	for i := 0; i < limit; i++ {
		item, ok, err := s.DB.ClaimQueue(c.Request.Context(), p.AccountID, who, kinds, now(), lease)
		if err != nil {
			return nil, err
		}
		if !ok {
			break
		}
		claimed = append(claimed, item)
	}
	if claimed == nil {
		claimed = []store.QueueItem{}
	}
	return gin.H{"items": claimed, "count": len(claimed)}, nil
}

func (s *Server) toolQueueAck(c *gin.Context, grant agentflow.Grant, id string, ack bool) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	item, err := s.DB.QueueByID(c.Request.Context(), p.AccountID, id)
	if err != nil {
		return nil, errString("queue item not found")
	}
	if item.Status != "claimed" {
		return nil, errString("queue item is not claimed")
	}
	who := p.UserID
	if who == "" {
		who = p.Actor
	}
	if item.ClaimedBy != who && p.Role != "admin" {
		return nil, errString("only the claimant can change this queue item")
	}
	if ack {
		item.Status = "acked"
		item.LeaseUntil = ""
	} else {
		item.Attempts++
		if item.Attempts >= 5 {
			item.Status = "dead"
		} else {
			item.Status = "open"
			item.ClaimedBy = ""
			item.LeaseUntil = ""
		}
	}
	if err := s.DB.SaveQueue(c.Request.Context(), item); err != nil {
		return nil, err
	}
	return gin.H{"item": item}, nil
}

func (s *Server) toolQueueList(c *gin.Context, grant agentflow.Grant, mine bool) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	claimedBy, status := "", ""
	if mine {
		claimedBy = p.UserID
		if claimedBy == "" {
			claimedBy = p.Actor
		}
		status = "claimed"
	}
	items, err := s.DB.ListQueue(c.Request.Context(), p.AccountID, claimedBy, status)
	if err != nil {
		return nil, err
	}
	if items == nil {
		items = []store.QueueItem{}
	}
	return gin.H{"items": items}, nil
}

func (s *Server) toolCreatePerson(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "outreach" && p.Role != "admin" {
		return nil, errString("only outreach or admin can write people")
	}
	name := strings.TrimSpace(strAny(args["name"]))
	if name == "" {
		return nil, errString("name is required")
	}
	person := store.Person{
		ID: newID("per_"), AccountID: p.AccountID, Name: name, Title: strAny(args["title"]),
		Company: strAny(args["company"]), JobID: strAny(args["job_id"]), Email: strAny(args["email"]),
		LinkedinURL: strAny(args["linkedin"]), Notes: strAny(args["notes"]),
		Touches: []byte("[]"), CreatedAt: now(), UpdatedAt: now(),
	}
	if err := s.DB.SavePerson(c.Request.Context(), person); err != nil {
		return nil, err
	}
	return gin.H{"person": person}, nil
}

func (s *Server) toolGetPerson(c *gin.Context, grant agentflow.Grant, id string) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "outreach" && p.Role != "admin" {
		return nil, errString("only outreach or admin can read people")
	}
	person, err := s.DB.Person(c.Request.Context(), p.AccountID, id)
	if err != nil {
		return nil, errString("person not found")
	}
	return gin.H{"person": person}, nil
}

func (s *Server) toolUpdatePerson(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "outreach" && p.Role != "admin" {
		return nil, errString("only outreach or admin can write people")
	}
	person, err := s.DB.Person(c.Request.Context(), p.AccountID, strAny(args["id"]))
	if err != nil {
		return nil, errString("person not found")
	}
	if v := strAny(args["name"]); v != "" {
		person.Name = v
	}
	if v := strAny(args["email"]); v != "" {
		person.Email = v
	}
	if v := strAny(args["linkedin"]); v != "" {
		person.LinkedinURL = v
	}
	if v := strAny(args["title"]); v != "" {
		person.Title = v
	}
	if v := strAny(args["notes"]); v != "" {
		person.Notes = v
	}
	if v := strAny(args["company"]); v != "" {
		person.Company = v
	}
	person.UpdatedAt = now()
	if err := s.DB.SavePerson(c.Request.Context(), person); err != nil {
		return nil, err
	}
	return gin.H{"person": person}, nil
}

func (s *Server) toolListSkills(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	rows, err := s.DB.ListSkills(c.Request.Context(), grant.AccountID, strAny(args["scope"]), strAny(args["status"]), strAny(args["tag"]))
	if err != nil {
		return nil, err
	}
	var visible []store.Skill
	for _, sk := range rows {
		if canSeeSkill(p, sk) {
			visible = append(visible, sk)
		}
	}
	if visible == nil {
		visible = []store.Skill{}
	}
	return gin.H{"skills": visible}, nil
}

func (s *Server) toolGetSkill(c *gin.Context, grant agentflow.Grant, id string) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	skill, err := s.DB.Skill(c.Request.Context(), id)
	if err != nil {
		skills, listErr := s.DB.ListSkills(c.Request.Context(), grant.AccountID, "", "", "")
		if listErr != nil {
			return nil, errString("skill not found")
		}
		for _, row := range skills {
			if (row.ID == id || row.Slug == id || row.Name == id) && canSeeSkill(p, row) {
				return gin.H{"skill": row}, nil
			}
		}
		return nil, errString("skill not found")
	}
	if skill.AccountID != grant.AccountID && skill.AccountID != "shared" && skill.Scope != "shared" {
		return nil, errString("skill not found")
	}
	if !canSeeSkill(p, skill) {
		return nil, errString("skill not found")
	}
	return gin.H{"skill": skill}, nil
}

func (s *Server) toolListMCPs(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	rows, err := s.DB.ListMCPs(c.Request.Context(), grant.AccountID)
	if err != nil {
		return nil, err
	}
	if rows == nil {
		rows = []store.MCP{}
	}
	return gin.H{"mcps": rows}, nil
}

func (s *Server) toolGetMCP(c *gin.Context, grant agentflow.Grant, id string) (gin.H, error) {
	item, err := s.DB.MCP(c.Request.Context(), grant.AccountID, id)
	if err != nil {
		return nil, errString("mcp not found")
	}
	return gin.H{"mcp": item}, nil
}

func (s *Server) toolDeleteMemory(c *gin.Context, grant agentflow.Grant, id string) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	item, err := s.DB.Memory(c.Request.Context(), grant.AccountID, id)
	if err != nil || !canReadPod(p, item.Pod) {
		return nil, errString("memory item not found")
	}
	if err := s.DB.DeleteMemory(c.Request.Context(), grant.AccountID, id); err != nil {
		return nil, errString("memory item not found")
	}
	s.invalidateRecall(c, grant.AccountID)
	return gin.H{"ok": true, "id": id}, nil
}

func (s *Server) toolSolidifyMemory(c *gin.Context, grant agentflow.Grant, id string) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	item, err := s.DB.Memory(c.Request.Context(), grant.AccountID, id)
	if err != nil || !canReadPod(p, item.Pod) {
		return nil, errString("memory item not found")
	}
	item.SolidifyStatus = "queued"
	item.UpdatedAt = now()
	_ = s.DB.SaveMemory(c.Request.Context(), item)
	rec := store.Recording{
		ID: newID("rec_"), AccountID: grant.AccountID, SkillID: item.ID, SubmitterID: p.UserID,
		Origin: "memory", Body: item.Body, Status: "pending", CreatedAt: now(),
	}
	_ = s.DB.SaveRecording(c.Request.Context(), rec)
	_ = s.DB.SaveQueue(c.Request.Context(), store.QueueItem{
		ID: newID("qi_"), AccountID: grant.AccountID, Kind: "skill.record", Track: "maintenance",
		Payload: mustJSON(gin.H{"recording_id": rec.ID}), Status: "open", DedupeKey: "skill.record:" + rec.ID, CreatedAt: now(),
	})
	s.invalidateRecall(c, grant.AccountID)
	return gin.H{"item": item, "recording": rec}, nil
}

func (s *Server) toolListEvents(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	limit := 50
	switch v := args["limit"].(type) {
	case float64:
		limit = int(v)
	case int:
		limit = v
	}
	events, err := s.DB.ListEvents(c.Request.Context(), grant.AccountID, strAny(args["job_id"]), limit)
	if err != nil {
		return nil, err
	}
	if events == nil {
		events = []store.Event{}
	}
	return gin.H{"events": events}, nil
}

func (s *Server) toolHeartbeat(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.UserID == "" {
		return gin.H{"ok": true, "compat": true}, nil
	}
	status := strAny(args["status"])
	if status == "" {
		status = "active"
	}
	pr := store.Presence{
		AccountID: p.AccountID, UserID: p.UserID, Status: status,
		TaskID: strAny(args["task_id"]), LastBeat: now(), UserAgent: "mcp",
	}
	_ = s.DB.SavePresence(c.Request.Context(), pr)
	return gin.H{"ok": true, "presence": pr}, nil
}

// Enhance update_job with more HTTP-parity fields while keeping lane gates.
func applyJobToolPatch(job *store.Job, args map[string]any) {
	if v := strAny(args["notes"]); v != "" {
		job.Notes = v
	}
	if v := strAny(args["url"]); v != "" {
		job.URL = v
	}
	if v := strAny(args["apply_url"]); v != "" {
		job.ApplyURL = v
	}
	if v := strAny(args["location"]); v != "" {
		job.Location = v
	}
	if v := strAny(args["description"]); v != "" {
		job.Description = v
	}
	if v := strAny(args["pay"]); v != "" {
		job.Pay = v
	}
	if raw, ok := args["apply_packet"]; ok {
		job.ApplyPacket = mustJSON(raw)
	}
	if raw, ok := args["outreach_packet"]; ok {
		job.OutreachPacket = mustJSON(raw)
	}
	if raw, ok := args["research"]; ok {
		job.Research = mustJSON(raw)
	}
}
