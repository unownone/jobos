package httpapi

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/unownone/jobos/server/internal/agentflow"
	"github.com/unownone/jobos/server/internal/store"
)

func (s *Server) toolMeta(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	return gin.H{
		"statuses": statuses, "apply_kinds": applyKinds,
		"roles":  []string{"discovery", "apply", "outreach", "admin", "maintenance"},
		"tracks": []string{"discovery", "application", "outreach", "maintenance"},
		"capabilities": capabilities(p.Role), "queue_kinds": queueKinds, "queue_lease_m": 15,
		"heartbeat_s": 10, "store": s.DB.Name(), "cache": s.Cache.Name(), "blob": s.Blobs.Name(),
		"candidate_onboarded": s.onboarded(c, p.AccountID),
		"mcp":                 true,
		"streams":             gin.H{"sse": "/api/stream", "websocket": "/ws", "poll_events": "MCP poll_events"},
		"auth":                "prefer long-lived Hub API key Bearer on /mcp",
	}, nil
}

func (s *Server) toolListInvites(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" {
		return nil, errString("admin only")
	}
	rows, err := s.DB.ListInvites(c.Request.Context(), p.AccountID)
	if err != nil {
		return nil, err
	}
	out := []gin.H{}
	for _, inv := range rows {
		out = append(out, publicInvite(inv))
	}
	return gin.H{"invites": out}, nil
}

func (s *Server) toolCreateInvite(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" {
		return nil, errString("admin only")
	}
	track := canonicalTrack(strAny(args["track"]))
	if track == "" {
		return nil, errString("unknown track")
	}
	mode := "owner_then_agents"
	if rawMode, ok := args["mode"]; ok {
		// Match HTTP: omit / empty → default; explicit invalid → reject.
		if s := strAny(rawMode); s != "" {
			mode = canonicalInviteMode(s)
			if mode == "" {
				return nil, errString("mode must be owner_then_agents, owner_only, or agents_only")
			}
		}
	}
	maxRedemptions := intAny(args["max_redemptions"], 5)
	if maxRedemptions <= 0 {
		maxRedemptions = 5
	}
	ttlHours := intAny(args["ttl_hours"], 72)
	if ttlHours <= 0 {
		ttlHours = 72
	}
	allowMultiple := truthy(args["allow_multiple_owners"])
	mcpBootstrap := true
	if raw, ok := args["mcp_bootstrap"]; ok {
		mcpBootstrap = truthy(raw)
	}
	secret := random(12)
	inv := store.Invite{
		ID: newID("inv_"), AccountID: p.AccountID, Track: track, Mode: mode, SecretHash: hash(secret),
		MaxRedemptions: maxRedemptions, ExpiresAt: time.Now().UTC().Add(time.Duration(ttlHours) * time.Hour).Format(time.RFC3339),
		CreatedBy: p.UserID, AllowMultipleOwners: allowMultiple, CreatedAt: now(),
	}
	if err := s.DB.CreateInvite(c.Request.Context(), inv); err != nil {
		return nil, err
	}
	origin := strings.TrimRight(s.publicURL(c), "/")
	out := gin.H{
		"invite": publicInvite(inv), "secret": secret,
		"join_url": origin + "/join/" + inv.ID + "?s=" + secret,
		"token":    "jh_inv_" + inv.ID + "." + secret,
		"mcp_url":  origin + "/mcp", "shown_once": true,
		"mcp_clients": []MCPClientSnippet{},
		"auth_hint":   "Paste an MCP client block. Bearer API key lasts ~90 days on /mcp.",
	}
	if !mcpBootstrap {
		return out, nil
	}
	kind, err := s.chooseJoinKind(c, inv)
	if err != nil {
		out["mcp_bootstrap_error"] = err.Error()
		return out, nil
	}
	user, apiKey, mintErr := s.mintInviteUser(c, inv, kind, "mcp-"+track+"-"+random(4), nil)
	if mintErr != nil {
		out["mcp_bootstrap_error"] = mintErr.Error()
		return out, nil
	}
	inv.Redemptions++
	_ = s.DB.SaveInvite(c.Request.Context(), inv)
	out["invite"] = publicInvite(inv)
	out["api_key"] = apiKey
	out["user"] = publicUser(user)
	out["mcp_clients"] = BuildMCPClientSnippets(origin, apiKey)
	return out, nil
}

func (s *Server) toolRevokeInvite(c *gin.Context, grant agentflow.Grant, id string) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" {
		return nil, errString("admin only")
	}
	inv, err := s.DB.Invite(c.Request.Context(), id)
	if err != nil || inv.AccountID != p.AccountID {
		return nil, errString("invite not found")
	}
	inv.RevokedAt = now()
	if err := s.DB.SaveInvite(c.Request.Context(), inv); err != nil {
		return nil, err
	}
	return gin.H{"invite": publicInvite(inv)}, nil
}

func (s *Server) toolListAgents(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Kind != "admin" && p.Kind != "owner" && p.Role != "admin" {
		return nil, errString("owner or admin only")
	}
	track := ""
	if p.Kind == "owner" {
		track = p.Track
	}
	users, err := s.DB.ListUsers(c.Request.Context(), p.AccountID, "", track)
	if err != nil {
		return nil, err
	}
	out := []gin.H{}
	for _, u := range users {
		if u.Kind == "agent" || u.Kind == "owner" {
			out = append(out, publicUser(u))
		}
	}
	return gin.H{"users": out}, nil
}

func (s *Server) toolCreateAgent(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Kind == "agent" || (p.Kind != "admin" && p.Kind != "owner" && p.Role != "admin") {
		return nil, errString("only a track owner or admin can mint agents")
	}
	display := strings.TrimSpace(strAny(args["display_name"]))
	track := p.Track
	if p.Role == "admin" || p.Kind == "admin" {
		track = canonicalTrack(strAny(args["track"]))
		if track == "" {
			track = p.Track
		}
	}
	if track == "" || display == "" {
		return nil, errString("display_name and track are required")
	}
	user := store.User{
		ID: newID("usr_"), AccountID: p.AccountID, Kind: "agent", Track: track,
		DisplayName: display, Metadata: []byte("{}"), CreatedBy: p.UserID, CreatedAt: now(),
	}
	if err := s.DB.CreateUser(c.Request.Context(), user); err != nil {
		return nil, err
	}
	plain := "jh_agt_" + random(16)
	_ = s.DB.CreateAPIKey(c.Request.Context(), store.APIKey{
		ID: newID("key_"), AccountID: p.AccountID, UserID: user.ID, Prefix: "jh_agt_", KeyHash: hash(plain), CreatedAt: now(),
	})
	return gin.H{"user": publicUser(user), "api_key": plain, "shown_once": true}, nil
}

func (s *Server) toolRotateAgentKey(c *gin.Context, grant agentflow.Grant, id string) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	user, err := s.DB.User(c.Request.Context(), id)
	if err != nil || user.AccountID != p.AccountID {
		return nil, errString("user not found")
	}
	if p.Role != "admin" && p.UserID != user.ID && !(p.Kind == "owner" && p.Track == user.Track) {
		return nil, errString("cannot manage this user")
	}
	_ = s.DB.RevokeUserKeys(c.Request.Context(), user.ID, now())
	s.bumpUser(c.Request.Context(), user.ID)
	plain := "jh_agt_" + random(16)
	prefix := "jh_agt_"
	if user.Kind == "owner" {
		plain = "jh_own_" + user.Track + "_" + random(12)
		prefix = "jh_own_" + user.Track + "_"
	}
	_ = s.DB.CreateAPIKey(c.Request.Context(), store.APIKey{
		ID: newID("key_"), AccountID: user.AccountID, UserID: user.ID, Prefix: prefix, KeyHash: hash(plain), CreatedAt: now(),
	})
	return gin.H{"user": publicUser(user), "api_key": plain, "shown_once": true}, nil
}

func (s *Server) toolDisableAgent(c *gin.Context, grant agentflow.Grant, id string) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" && p.Kind != "owner" {
		return nil, errString("owner or admin only")
	}
	user, err := s.DB.User(c.Request.Context(), id)
	if err != nil || user.AccountID != p.AccountID {
		return nil, errString("user not found")
	}
	if user.Kind == "admin" {
		return nil, errString("cannot disable admin")
	}
	if p.Role != "admin" && p.Track != user.Track {
		return nil, errString("owners can disable users on their own track")
	}
	user.DisabledAt = now()
	_ = s.DB.SaveUser(c.Request.Context(), user)
	_ = s.DB.RevokeUserKeys(c.Request.Context(), user.ID, now())
	s.bumpUser(c.Request.Context(), user.ID)
	return gin.H{"user": publicUser(user)}, nil
}

func (s *Server) toolPutCandidate(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" && p.Kind != "admin" {
		return nil, errString("admin only")
	}
	yamlText := strAny(args["yaml"])
	if yamlText == "" {
		return nil, errString("candidate yaml is required")
	}
	if missing := profileMissing(yamlText); missing != "" {
		return nil, errString("profile is incomplete: " + missing)
	}
	if err := s.Blobs.Put(c.Request.Context(), p.AccountID, candidateKey, []byte(yamlText), "text/yaml", "candidate.yaml"); err != nil {
		return nil, err
	}
	_ = s.Cache.DeletePrefix(c.Request.Context(), "cand:"+p.AccountID)
	return gin.H{"ok": true, "onboarded": s.onboarded(c, p.AccountID)}, nil
}

func (s *Server) toolGetResume(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "apply" && p.Role != "outreach" && p.Role != "admin" {
		return nil, errString("only apply, outreach, or admin can download the resume PDF")
	}
	obj, err := s.Blobs.Get(c.Request.Context(), p.AccountID, resumeKey)
	if err != nil {
		return gin.H{"present": false}, nil
	}
	return gin.H{
		"present": true, "bytes": len(obj.Content), "content_type": "application/pdf",
		"base64": base64.StdEncoding.EncodeToString(obj.Content),
	}, nil
}

func (s *Server) toolPutResume(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" {
		return nil, errString("admin only")
	}
	raw := strAny(args["base64"])
	if raw == "" {
		return nil, errString("resume base64 is required")
	}
	body, err := base64.StdEncoding.DecodeString(raw)
	if err != nil || len(body) < 5 {
		return nil, errString("invalid resume base64")
	}
	if err := s.Blobs.Put(c.Request.Context(), p.AccountID, resumeKey, body, "application/pdf", resumeKey); err != nil {
		return nil, err
	}
	return gin.H{"ok": true, "bytes": len(body), "driver": s.Blobs.Name()}, nil
}

func (s *Server) toolMemoryPods(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	pods := []string{"worker:" + p.UserID}
	if p.Role == "admin" || p.Role == "maintenance" {
		for _, track := range hubTracks {
			pods = append(pods, "track:"+track)
		}
	} else if p.Track != "" {
		pods = append(pods, "track:"+p.Track)
	}
	pods = append(pods, "common")
	return gin.H{
		"pods": pods,
		"write_policy": gin.H{
			"window_s": 15 * 60,
			"caps":     gin.H{"worker": 6, "track": 3, "common": 2},
		},
		"kinds": memoryKinds,
	}, nil
}

func (s *Server) toolPatchMemory(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	item, err := s.DB.Memory(c.Request.Context(), p.AccountID, strAny(args["id"]))
	if err != nil || !canReadPod(p, item.Pod) {
		return nil, errString("memory item not found")
	}
	if v := strAny(args["title"]); v != "" {
		item.Title = strings.Join(strings.Fields(v), " ")
	}
	if v := strAny(args["body"]); v != "" {
		item.Body = strings.TrimSpace(v)
	}
	if v := strAny(args["kind"]); v != "" {
		item.Kind = strings.ToLower(strings.TrimSpace(v))
	}
	if errText := validateMemory(item.Pod, item.Kind, item.Title, item.Body); errText != "" {
		return nil, errString(errText)
	}
	item.UpdatedAt = now()
	if err := s.DB.SaveMemory(c.Request.Context(), item); err != nil {
		return nil, err
	}
	s.invalidateRecall(c, p.AccountID)
	return gin.H{"item": item}, nil
}

func (s *Server) toolMoveMemory(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	item, err := s.DB.Memory(c.Request.Context(), p.AccountID, strAny(args["id"]))
	if err != nil || !canReadPod(p, item.Pod) {
		return nil, errString("memory item not found")
	}
	pod, msg := resolveWritePod(p, strAny(args["pod"]))
	if msg != "" {
		return nil, errString(msg)
	}
	kind := item.Kind
	if v := strAny(args["kind"]); v != "" {
		kind = strings.ToLower(v)
	}
	if errText := validateMemory(pod, kind, item.Title, item.Body); errText != "" {
		return nil, errString(errText)
	}
	keepOriginal := truthy(args["keep_original"])
	moved := item
	moved.Pod = pod
	moved.Kind = kind
	moved.UpdatedAt = now()
	moved.ExpiresAt = defaultExpiry(pod, kind, item.Importance)
	if keepOriginal {
		moved.ID = newID("mem_")
		moved.CreatedAt = now()
	}
	if err := s.DB.SaveMemory(c.Request.Context(), moved); err != nil {
		return nil, err
	}
	s.invalidateRecall(c, p.AccountID)
	return gin.H{"item": moved, "copied": keepOriginal}, nil
}

func (s *Server) toolListPresence(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	rows, err := s.DB.ListPresence(c.Request.Context(), p.AccountID)
	if err != nil {
		return nil, err
	}
	if rows == nil {
		rows = []store.Presence{}
	}
	return gin.H{"presence": rows}, nil
}

func (s *Server) toolGetPresence(c *gin.Context, grant agentflow.Grant, userID string) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	rows, err := s.DB.ListPresence(c.Request.Context(), p.AccountID)
	if err != nil {
		return nil, err
	}
	for _, row := range rows {
		if row.UserID == userID {
			return gin.H{"presence": row}, nil
		}
	}
	return nil, errString("presence not found")
}

func (s *Server) toolCreateMessage(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	body := strings.TrimSpace(strAny(args["body"]))
	if body == "" {
		return nil, errString("body is required")
	}
	msgType := strAny(args["type"])
	if msgType == "" {
		msgType = "note"
	}
	msg := store.Message{
		ID: newID("msg_"), AccountID: p.AccountID, FromUserID: p.UserID,
		ToUserID: strAny(args["to_user_id"]), ToTrack: strAny(args["to_track"]),
		JobID: strAny(args["job_id"]), Type: msgType, Body: body, CreatedAt: now(),
	}
	if err := s.DB.SaveMessage(c.Request.Context(), msg); err != nil {
		return nil, err
	}
	s.RT.Publish(p.AccountID, "message", gin.H{"id": msg.ID, "type": msg.Type})
	return gin.H{"message": msg}, nil
}

func (s *Server) toolListMessages(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	unread := truthy(args["unread"])
	rows, err := s.DB.ListMessages(c.Request.Context(), p.AccountID, unread)
	if err != nil {
		return nil, err
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
	return gin.H{"messages": visible}, nil
}

func (s *Server) toolReadMessage(c *gin.Context, grant agentflow.Grant, id string) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	msg, err := s.DB.Message(c.Request.Context(), p.AccountID, id)
	if err != nil || !canSeeMessage(p, msg) {
		return nil, errString("message not found")
	}
	msg.ReadAt = now()
	_ = s.DB.SaveMessage(c.Request.Context(), msg)
	return gin.H{"message": msg}, nil
}

func (s *Server) toolCreateSkill(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	name := strings.TrimSpace(strAny(args["name"]))
	body := strAny(args["body"])
	if name == "" || body == "" {
		return nil, errString("name and body are required")
	}
	sk := store.Skill{
		ID: newID("skl_"), AccountID: p.AccountID, Name: name, Body: body,
		Scope: "local", Status: "draft", Kind: strAny(args["kind"]), OwnerID: p.UserID,
		Origin: "recording", Version: 1, Tags: []byte("[]"), CreatedAt: now(), UpdatedAt: now(),
	}
	if sk.Kind == "" {
		sk.Kind = "skill"
	}
	if raw, ok := args["tags"]; ok {
		sk.Tags = mustJSON(raw)
	}
	if err := s.DB.SaveSkill(c.Request.Context(), sk); err != nil {
		return nil, err
	}
	return gin.H{"skill": sk}, nil
}

func (s *Server) toolPatchSkill(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	sk, err := s.DB.Skill(c.Request.Context(), strAny(args["id"]))
	if err != nil {
		return nil, errString("skill not found")
	}
	if sk.Scope == "shared" && p.Role != "admin" && p.Role != "maintenance" {
		return nil, errString("shared skills are maintainer-owned")
	}
	if sk.Scope == "local" && sk.OwnerID != "" && sk.OwnerID != p.UserID && p.Role != "admin" {
		return nil, errString("not your skill")
	}
	if v := strAny(args["name"]); v != "" {
		sk.Name = v
	}
	if v := strAny(args["body"]); v != "" {
		sk.Body = v
	}
	if v := strAny(args["status"]); v != "" {
		if v == "approved" && p.Role != "admin" && p.Role != "maintenance" {
			return nil, errString("shared skills are published through proctor")
		}
		sk.Status = v
	}
	if raw, ok := args["tags"]; ok {
		sk.Tags = mustJSON(raw)
	}
	sk.Version++
	sk.UpdatedAt = now()
	if err := s.DB.SaveSkill(c.Request.Context(), sk); err != nil {
		return nil, err
	}
	return gin.H{"skill": sk}, nil
}

func (s *Server) toolForkSkill(c *gin.Context, grant agentflow.Grant, id string) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	src, err := s.DB.Skill(c.Request.Context(), id)
	if err != nil || !canSeeSkill(p, src) {
		return nil, errString("skill not found")
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
		return nil, err
	}
	return gin.H{"skill": fork}, nil
}

func (s *Server) toolCreateRecording(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	origin := strAny(args["origin"])
	if origin == "" {
		origin = "recording"
	}
	rec := store.Recording{
		ID: newID("rec_"), AccountID: p.AccountID, SkillID: strAny(args["skill_id"]),
		SubmitterID: p.UserID, Origin: origin, Body: strAny(args["body"]), Status: "pending", CreatedAt: now(),
	}
	_ = s.DB.SaveRecording(c.Request.Context(), rec)
	_ = s.DB.SaveQueue(c.Request.Context(), store.QueueItem{
		ID: newID("qi_"), AccountID: p.AccountID, Kind: "skill.record", Track: "maintenance",
		Status: "open", DedupeKey: "skill.record:" + rec.ID,
		Payload: mustJSON(gin.H{"recording_id": rec.ID}), CreatedAt: now(),
	})
	return gin.H{"recording": rec}, nil
}

func (s *Server) toolListRecordings(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	rows, err := s.DB.ListRecordings(c.Request.Context(), p.AccountID, strAny(args["status"]))
	if err != nil {
		return nil, err
	}
	if rows == nil {
		rows = []store.Recording{}
	}
	return gin.H{"recordings": rows}, nil
}

func (s *Server) toolGetRecording(c *gin.Context, grant agentflow.Grant, id string) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	rows, err := s.DB.ListRecordings(c.Request.Context(), p.AccountID, "")
	if err != nil {
		return nil, err
	}
	for _, row := range rows {
		if row.ID == id {
			return gin.H{"recording": row}, nil
		}
	}
	return nil, errString("recording not found")
}

func (s *Server) toolSetRecording(c *gin.Context, grant agentflow.Grant, id, force string, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" && p.Role != "maintenance" {
		return nil, errString("maintainer only")
	}
	rec, err := s.DB.Recording(c.Request.Context(), id)
	if errors.Is(err, store.ErrNotFound) {
		return nil, errString("recording not found")
	}
	if err != nil {
		return nil, err
	}
	if force != "" {
		rec.Status = force
	} else if v := strAny(args["status"]); v != "" {
		rec.Status = v
	}
	if v := strAny(args["note"]); v != "" {
		rec.Note = v
	}
	_ = s.DB.SaveRecording(c.Request.Context(), rec)
	if rec.Status == "promoted" && rec.SkillID != "" {
		if sk, err := s.DB.Skill(c.Request.Context(), rec.SkillID); err == nil {
			sk.Status = "approved"
			sk.Scope = "shared"
			sk.UpdatedAt = now()
			_ = s.DB.SaveSkill(c.Request.Context(), sk)
		}
	}
	return gin.H{"recording": rec}, nil
}

func (s *Server) toolHygiene(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" && p.Role != "maintenance" {
		return nil, errString("only admin or maintenance can run hygiene")
	}
	counts, err := s.DB.CountByStatus(c.Request.Context(), p.AccountID)
	if err != nil {
		return nil, err
	}
	return gin.H{"counts": counts}, nil
}

func (s *Server) toolVacuum(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" && p.Role != "maintenance" {
		return nil, errString("only admin or maintenance can run hygiene")
	}
	return gin.H{"ok": true, "note": "autovacuum owns Postgres; the Go hub does not run VACUUM inside a request"}, nil
}

func (s *Server) toolImportJobs(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" && p.Role != "maintenance" {
		return nil, errString("only admin or maintenance can import history")
	}
	rawJobs, _ := args["jobs"].([]any)
	n := 0
	for _, item := range rawJobs {
		raw, ok := item.(map[string]any)
		if !ok {
			continue
		}
		company, title := strAny(raw["company"]), strAny(raw["title"])
		if company == "" || title == "" {
			continue
		}
		id := strAny(raw["id"])
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
	return gin.H{"imported": n}, nil
}

func (s *Server) toolExportLedger(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" && p.Role != "maintenance" {
		return nil, errString("only admin or maintenance can export the ledger")
	}
	jobs, _, _, err := s.DB.ListJobs(c.Request.Context(), store.JobFilter{AccountID: p.AccountID})
	if err != nil {
		return nil, err
	}
	if jobs == nil {
		jobs = []store.Job{}
	}
	events, _ := s.DB.ListEvents(c.Request.Context(), p.AccountID, "", 500)
	if events == nil {
		events = []store.Event{}
	}
	return gin.H{"jobs": jobs, "events": events, "exported_at": now()}, nil
}

func (s *Server) toolSkillsZip(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	data, track, err := s.buildSkillsZip(p)
	if err != nil {
		return nil, err
	}
	return gin.H{
		"track": track, "bytes": len(data), "content_type": "application/zip",
		"filename": "skills-" + track + ".zip",
		"base64":   base64.StdEncoding.EncodeToString(data),
	}, nil
}

func (s *Server) toolRebuildPack(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" && p.Role != "maintenance" {
		return nil, errString("maintainer only")
	}
	n := s.Seed(c.Request.Context())
	_, _ = s.DB.AddEvent(c.Request.Context(), store.Event{AccountID: p.AccountID, TS: now(), ActorRole: p.Role, Actor: p.Actor, Action: "pack_rebuild"})
	return gin.H{"ok": true, "seeded": n}, nil
}

func (s *Server) toolDashboard(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	counts, err := s.DB.CountByStatus(c.Request.Context(), p.AccountID)
	if err != nil {
		return nil, err
	}
	return gin.H{
		"counts": counts, "candidate_onboarded": s.onboarded(c, p.AccountID),
		"cache": s.Cache.Name(), "blob": s.Blobs.Name(),
	}, nil
}

func (s *Server) toolListUsers(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	kind := strAny(args["kind"])
	track := strAny(args["track"])
	rows, err := s.DB.ListUsers(c.Request.Context(), p.AccountID, kind, track)
	if err != nil {
		return nil, err
	}
	out := []gin.H{}
	for _, user := range rows {
		out = append(out, publicUser(user))
	}
	return gin.H{"users": out, "count": len(out)}, nil
}

func (s *Server) toolSeedRegistry(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" && p.Role != "maintenance" {
		return nil, errString("maintainer only")
	}
	n := s.Seed(c.Request.Context())
	return gin.H{"seeded": n}, nil
}

func (s *Server) toolAddTokenBurn(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	toolName := strAny(args["tool_name"])
	if toolName == "" {
		return nil, errString("tool_name is required")
	}
	b := store.Burn{
		AccountID: p.AccountID, TS: now(), ToolName: toolName,
		Skill: strAny(args["skill"]), Lane: strAny(args["lane"]), JobID: strAny(args["job_id"]),
		PromptTokens: intAny(args["prompt_tokens"], 0), CompletionTokens: intAny(args["completion_tokens"], 0),
		TotalTokens: intAny(args["total_tokens"], 0), CostUSD: floatAny(args["cost_usd"]),
		ActorRole: p.Role, Actor: p.Actor,
	}
	if b.TotalTokens == 0 {
		b.TotalTokens = b.PromptTokens + b.CompletionTokens
	}
	saved, err := s.DB.AddBurn(c.Request.Context(), b)
	if err != nil {
		return nil, err
	}
	return gin.H{"burn": saved}, nil
}

func (s *Server) toolListTokenBurns(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" && p.Role != "maintenance" {
		return nil, errString("only admin or maintenance can read metrics")
	}
	limit := intAny(args["limit"], 100)
	rows, err := s.DB.ListBurns(c.Request.Context(), p.AccountID, limit)
	if err != nil {
		return nil, err
	}
	if rows == nil {
		rows = []store.Burn{}
	}
	return gin.H{"burns": rows}, nil
}

func (s *Server) toolTokenBurnSummary(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	if p.Role != "admin" && p.Role != "maintenance" {
		return nil, errString("only admin or maintenance can read metrics")
	}
	rows, err := s.DB.ListBurns(c.Request.Context(), p.AccountID, 1000)
	if err != nil {
		return nil, err
	}
	var prompt, completion int
	var cost float64
	for _, b := range rows {
		prompt += b.PromptTokens
		completion += b.CompletionTokens
		cost += b.CostUSD
	}
	return gin.H{"count": len(rows), "prompt_tokens": prompt, "completion_tokens": completion, "cost_usd": cost}, nil
}

func (s *Server) toolA2ADirectory(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
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
		return nil, err
	}
	if peers == nil {
		peers = []store.Peer{}
	}
	return gin.H{"local": local, "peers": peers, "protocolVersion": "0.3.0"}, nil
}

func (s *Server) toolListPeers(c *gin.Context, grant agentflow.Grant) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	rows, err := s.DB.ListPeers(c.Request.Context(), p.AccountID)
	if err != nil {
		return nil, err
	}
	if rows == nil {
		rows = []store.Peer{}
	}
	return gin.H{"peers": rows}, nil
}

func (s *Server) toolCreatePeer(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	url := strings.TrimSpace(strAny(args["url"]))
	if url == "" {
		return nil, errString("url is required")
	}
	peer := store.Peer{ID: newID("peer_"), AccountID: p.AccountID, Name: strAny(args["name"]), URL: url, CreatedAt: now()}
	if err := s.DB.SavePeer(c.Request.Context(), peer); err != nil {
		return nil, err
	}
	return gin.H{"peer": peer}, nil
}

func (s *Server) toolSendPeer(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	peerID := strAny(args["id"])
	if peerID == "" {
		return nil, errString("id is required")
	}
	payload := args["payload"]
	if payload == nil {
		payload = args
	}
	task := store.Task{ID: newID("task_"), AccountID: p.AccountID, State: "submitted", Payload: mustJSON(payload), CreatedAt: now()}
	_ = s.DB.SaveTask(c.Request.Context(), task)
	return gin.H{"task": task, "peer_id": peerID}, nil
}

func (s *Server) toolPollEvents(c *gin.Context, grant agentflow.Grant, args map[string]any) (gin.H, error) {
	p, err := s.principalFromGrant(c, grant)
	if err != nil {
		return nil, err
	}
	after := int64(intAny(args["after_seq"], 0))
	limit := intAny(args["limit"], 32)
	hubEpoch := s.RT.Epoch()
	reset := false
	if after > 0 {
		if rawEpoch, ok := args["epoch"]; ok {
			if strAny(rawEpoch) != hubEpoch {
				after = 0
				reset = true
			}
		} else if after > s.RT.CurrentSeq() {
			// Stale cursor from a prior Hub process (seq restarted at 0).
			after = 0
			reset = true
		}
	}
	events := s.RT.Recent(p.AccountID, after, limit)
	out := make([]gin.H, 0, len(events))
	var last int64 = after
	for _, ev := range events {
		out = append(out, gin.H{"seq": ev.Seq, "event": ev.Event, "data": ev.Data})
		if ev.Seq > last {
			last = ev.Seq
		}
	}
	return gin.H{
		"events": out, "count": len(out), "after_seq": after, "next_seq": last,
		"epoch": hubEpoch, "cursor_reset": reset,
		"hint": "MCP poll equivalent of /ws and /api/stream. Pass epoch and next_seq as after_seq on the next call.",
	}, nil
}

func intAny(v any, fallback int) int {
	switch n := v.(type) {
	case float64:
		return int(n)
	case int:
		return n
	case int64:
		return int(n)
	case json.Number:
		i, err := n.Int64()
		if err == nil {
			return int(i)
		}
	case string:
		i, err := strconv.Atoi(strings.TrimSpace(n))
		if err == nil {
			return i
		}
	}
	return fallback
}

func floatAny(v any) float64 {
	switch n := v.(type) {
	case float64:
		return n
	case float32:
		return float64(n)
	case int:
		return float64(n)
	case json.Number:
		f, err := n.Float64()
		if err == nil {
			return f
		}
	case string:
		f, err := strconv.ParseFloat(strings.TrimSpace(n), 64)
		if err == nil {
			return f
		}
	}
	return 0
}
