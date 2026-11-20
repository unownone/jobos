package httpapi

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/unownone/jobos/server/internal/store"
)

func rpcError(id any, code int, message string) gin.H {
	return gin.H{"jsonrpc": "2.0", "id": id, "error": gin.H{"code": code, "message": message}}
}

func rpcResult(id any, result any) gin.H {
	return gin.H{"jsonrpc": "2.0", "id": id, "result": result}
}

func (s *Server) a2a(c *gin.Context) {
	var payload map[string]any
	if err := c.ShouldBindJSON(&payload); err != nil || payload == nil {
		c.JSON(http.StatusOK, rpcError(nil, -32700, "parse error"))
		return
	}
	id := payload["id"]
	if payload["jsonrpc"] != "2.0" {
		c.JSON(http.StatusOK, rpcError(id, -32600, "jsonrpc must be 2.0"))
		return
	}
	method, _ := payload["method"].(string)
	params, _ := payload["params"].(map[string]any)
	if params == nil {
		params = map[string]any{}
	}
	var principal *principal
	if p, err := s.authenticate(c); err == nil {
		principal = &p
	}
	track := canonicalTrack(c.Param("track"))
	if c.Param("track") != "" && track == "" {
		c.JSON(http.StatusNotFound, gin.H{"detail": "unknown track"})
		return
	}
	c.JSON(http.StatusOK, s.a2aCall(c, id, method, params, principal, track))
}

func (s *Server) a2aCall(c *gin.Context, id any, method string, params map[string]any, p *principal, track string) gin.H {
	switch method {
	case "agent/getAuthenticatedExtendedCard":
		if p == nil {
			return rpcError(id, -32091, "Authorization Bearer required")
		}
		return rpcResult(id, gin.H{"name": "jobOS", "protocolVersion": "0.3.0", "track": track, "url": s.publicURL(c) + "/a2a"})
	case "tasks/get", "tasks/cancel":
		if p == nil {
			return rpcError(id, -32091, "Authorization Bearer required")
		}
		taskID, _ := params["id"].(string)
		if taskID == "" {
			if alt, _ := params["taskId"].(string); alt != "" {
				taskID = alt
			}
		}
		if taskID == "" {
			return rpcError(id, -32602, "id is required")
		}
		stored, err := s.DB.Task(c.Request.Context(), p.AccountID, taskID)
		if err != nil {
			return rpcError(id, -32001, "task not found")
		}
		if method == "tasks/get" {
			if len(stored.Payload) > 2 {
				var result any
				if json.Unmarshal(stored.Payload, &result) == nil {
					return rpcResult(id, result)
				}
			}
			return rpcResult(id, gin.H{"id": stored.ID, "status": gin.H{"state": stored.State}})
		}
		if stored.State == "completed" || stored.State == "canceled" || stored.State == "failed" || stored.State == "rejected" {
			return rpcError(id, -32002, "task is not cancelable")
		}
		stored.State = "canceled"
		result := gin.H{"id": stored.ID, "status": gin.H{"state": "canceled"}}
		stored.Payload = mustJSON(result)
		_ = s.DB.SaveTask(c.Request.Context(), stored)
		return rpcResult(id, result)
	case "tasks/list":
		if p == nil {
			return rpcError(id, -32091, "Authorization Bearer required")
		}
		limit := 50
		if n, ok := params["limit"].(float64); ok && n > 0 {
			limit = int(n)
		}
		rows, err := s.DB.ListTasks(c.Request.Context(), p.AccountID, limit)
		if err != nil {
			return rpcError(id, -32603, err.Error())
		}
		tasks := []any{}
		for _, row := range rows {
			if len(row.Payload) > 2 {
				var stored any
				if json.Unmarshal(row.Payload, &stored) == nil {
					tasks = append(tasks, stored)
					continue
				}
			}
			tasks = append(tasks, gin.H{"id": row.ID, "status": gin.H{"state": row.State}})
		}
		return rpcResult(id, gin.H{"tasks": tasks})
	case "message/stream", "tasks/resubscribe":
		return rpcError(id, -32601, "streaming is not enabled; use message/send")
	case "message/send":
		return s.a2aSend(c, id, params, p, track)
	default:
		return rpcError(id, -32601, "unknown method "+method)
	}
}

func (s *Server) a2aSend(c *gin.Context, id any, params map[string]any, p *principal, track string) gin.H {
	if p == nil {
		return s.a2aAuthRequired(c, id)
	}
	if !s.onboarded(c, p.AccountID) {
		return rpcError(id, -32090, "Onboard the candidate profile before A2A sends")
	}
	message, _ := params["message"].(map[string]any)
	data := messageData(message)
	text := messageText(message)
	if text == "" {
		if body, _ := data["body"].(string); strings.TrimSpace(body) != "" {
			text = strings.TrimSpace(body)
		}
	}
	if text == "" {
		return rpcError(id, -32602, "message text is required")
	}
	toTrack, errMsg := a2aTrack(data, params, track)
	if errMsg != "" {
		return rpcError(id, -32602, errMsg)
	}
	if toTrack == "" {
		toTrack = p.Track
	}
	if toTrack == "" {
		toTrack = "application"
	}
	toUser, _ := data["to_user_id"].(string)
	jobID, _ := data["job_id"].(string)
	msgType := a2aMessageType(data)
	if toUser != "" {
		toTrack = ""
	}
	msg := store.Message{
		ID: newID("msg_"), AccountID: p.AccountID, FromUserID: p.UserID, ToUserID: toUser, ToTrack: toTrack,
		JobID: jobID, Type: msgType, Body: text, CreatedAt: now(),
	}
	if err := s.DB.SaveMessage(c.Request.Context(), msg); err != nil {
		return rpcError(id, -32603, err.Error())
	}
	_, _ = s.DB.AddEvent(c.Request.Context(), store.Event{
		AccountID: p.AccountID, TS: now(), ActorRole: p.Role, Actor: p.Actor, Action: "a2a_message_send", JobID: jobID, Note: msgType,
	})
	dest := toUser
	if dest == "" {
		dest = toTrack
	}
	contextID, _ := message["contextId"].(string)
	if contextID == "" {
		contextID, _ = message["context_id"].(string)
	}
	reply := "Hub accepted " + msgType + " for " + dest + "."
	result := gin.H{
		"id": "", "contextId": contextID,
		"status": gin.H{"state": "completed"},
		"history": []any{
			message,
			gin.H{"role": "agent", "parts": []any{
				gin.H{"kind": "text", "text": reply},
				gin.H{"kind": "data", "data": gin.H{"hub_message_id": msg.ID, "type": msgType, "to_track": toTrack, "to_user_id": toUser, "job_id": jobID}},
			}},
		},
		"artifacts": []any{gin.H{"artifactId": msg.ID, "name": "hub-inbox", "parts": []any{gin.H{"kind": "data", "data": gin.H{"message": msg}}}}},
		"metadata":  gin.H{"protocol": "A2A", "hub": "job-apply-os"},
	}
	task := store.Task{ID: newID("task_"), AccountID: p.AccountID, Track: track, State: "completed", CreatedAt: now()}
	result["id"] = task.ID
	task.Payload = mustJSON(result)
	_ = s.DB.SaveTask(c.Request.Context(), task)
	s.RT.Publish(p.AccountID, "message", gin.H{"id": msg.ID, "type": msg.Type})
	return rpcResult(id, result)
}

func (s *Server) a2aAuthRequired(c *gin.Context, id any) gin.H {
	admin, err := s.DB.FirstAdmin(c.Request.Context())
	if err != nil || !s.onboarded(c, admin.AccountID) {
		return rpcError(id, -32090, "Onboard the candidate profile before A2A sends")
	}
	task := store.Task{ID: newID("task_"), AccountID: admin.AccountID, State: "auth-required", CreatedAt: now()}
	result := gin.H{
		"id":     task.ID,
		"status": gin.H{"state": "auth-required"},
		"history": []any{gin.H{"role": "agent", "parts": []any{
			gin.H{"kind": "text", "text": "Send Authorization: Bearer $HUB_KEY (owner or agent key)."},
		}}},
	}
	task.Payload = mustJSON(result)
	_ = s.DB.SaveTask(c.Request.Context(), task)
	return rpcResult(id, result)
}

func messageData(message map[string]any) map[string]any {
	out := map[string]any{}
	if meta, _ := message["metadata"].(map[string]any); meta != nil {
		for k, v := range meta {
			out[k] = v
		}
	}
	if data, _ := message["data"].(map[string]any); data != nil {
		for k, v := range data {
			out[k] = v
		}
	}
	parts, _ := message["parts"].([]any)
	for _, part := range parts {
		obj, _ := part.(map[string]any)
		if partKind(obj) != "data" {
			continue
		}
		data, _ := obj["data"].(map[string]any)
		for k, v := range data {
			out[k] = v
		}
	}
	return out
}

func messageText(message map[string]any) string {
	if message == nil {
		return ""
	}
	var chunks []string
	parts, _ := message["parts"].([]any)
	for _, part := range parts {
		obj, _ := part.(map[string]any)
		if partKind(obj) != "text" && partKind(obj) != "text/plain" {
			continue
		}
		if text, _ := obj["text"].(string); strings.TrimSpace(text) != "" {
			chunks = append(chunks, strings.TrimSpace(text))
		}
	}
	if len(chunks) > 0 {
		return strings.Join(chunks, "\n")
	}
	if text, _ := message["text"].(string); strings.TrimSpace(text) != "" {
		return strings.TrimSpace(text)
	}
	if text, _ := message["body"].(string); strings.TrimSpace(text) != "" {
		return strings.TrimSpace(text)
	}
	return ""
}

func partKind(part map[string]any) string {
	if part == nil {
		return ""
	}
	if kind, _ := part["kind"].(string); kind != "" {
		return strings.ToLower(strings.TrimSpace(kind))
	}
	kind, _ := part["type"].(string)
	return strings.ToLower(strings.TrimSpace(kind))
}

func a2aTrack(data map[string]any, params map[string]any, fallback string) (string, string) {
	raw, _ := data["to_track"].(string)
	if raw == "" {
		raw, _ = data["track"].(string)
	}
	if strings.TrimSpace(raw) != "" {
		if canon := canonicalTrack(raw); canon != "" {
			return canon, ""
		}
		if strings.EqualFold(strings.TrimSpace(raw), "admin") {
			return "admin", ""
		}
		return "", "to_track must be a Hub track or admin"
	}
	skill, _ := data["skill_id"].(string)
	if skill == "" {
		skill, _ = data["skill"].(string)
	}
	if skill == "" {
		skill, _ = params["skill"].(string)
	}
	return skillTrack(skill, fallback), ""
}

func skillTrack(skill, fallback string) string {
	switch strings.ToLower(strings.TrimSpace(skill)) {
	case "", "hub.handoff":
		return fallback
	case "hub.discovery", "discovery":
		return "discovery"
	case "hub.application", "hub.apply", "application", "apply":
		return "application"
	case "hub.outreach", "outreach":
		return "outreach"
	case "hub.maintenance", "maintenance", "maintainer":
		return "maintenance"
	default:
		if canon := canonicalTrack(skill); canon != "" {
			return canon
		}
		return fallback
	}
}

func a2aMessageType(data map[string]any) string {
	raw, _ := data["type"].(string)
	if raw == "" {
		raw, _ = data["kind"].(string)
	}
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "note", "block", "handoff", "question":
		return strings.ToLower(strings.TrimSpace(raw))
	default:
		return "note"
	}
}
