package httpapi

import "encoding/json"

var statuses = []string{
	"discovered", "enriching", "shortlisted", "skipped", "apply_ready", "applying", "applied",
	"apply_blocked", "outreach_ready", "outreaching", "waiting", "chatting", "interview", "offer",
	"rejected", "closed_rejected", "closed_withdrawn", "closed_expired",
}

var discoveryLane = map[string]bool{
	"discovered": true, "enriching": true, "shortlisted": true, "skipped": true, "apply_ready": true,
}
var applyLane = map[string]bool{
	"apply_ready": true, "applying": true, "applied": true, "apply_blocked": true, "outreach_ready": true, "closed_expired": true,
}
var outreachLane = map[string]bool{
	"applied": true, "outreach_ready": true, "outreaching": true, "waiting": true, "chatting": true,
	"interview": true, "offer": true, "closed_rejected": true, "closed_withdrawn": true,
}

var applyKinds = []string{"ats", "linkedin_easy_apply", "indeed", "network", "outreach_only", "unknown"}

var queueKinds = []string{
	"catalog.refresh", "discovery.search", "discovery.enrich", "discovery.packet",
	"apply.ready", "apply.blocked_retry", "outreach.ready",
	"maintenance.hygiene", "maintenance.pack_rebuild", "skill.record",
}

var kindTrack = map[string]string{
	"catalog.refresh": "", "discovery.search": "discovery", "discovery.enrich": "discovery",
	"discovery.packet": "discovery", "apply.ready": "application", "apply.blocked_retry": "application",
	"outreach.ready": "outreach", "maintenance.hygiene": "maintenance",
	"maintenance.pack_rebuild": "maintenance", "skill.record": "maintenance",
}

func produceKinds(role string) []string {
	switch role {
	case "discovery":
		return []string{"catalog.refresh", "discovery.search", "discovery.enrich", "discovery.packet", "skill.record"}
	case "apply", "outreach":
		return []string{"skill.record"}
	case "maintenance":
		return []string{"catalog.refresh", "maintenance.hygiene", "maintenance.pack_rebuild", "skill.record"}
	case "admin":
		return append([]string{}, queueKinds...)
	default:
		return nil
	}
}

func systemQueueKind(kind string) bool {
	return kind == "apply.ready" || kind == "outreach.ready"
}

func consumeKinds(role string) []string {
	switch role {
	case "discovery":
		return []string{"catalog.refresh", "discovery.search", "discovery.enrich", "discovery.packet"}
	case "apply":
		return []string{"apply.ready", "apply.blocked_retry"}
	case "outreach":
		return []string{"outreach.ready"}
	case "maintenance":
		return []string{"catalog.refresh", "maintenance.hygiene", "maintenance.pack_rebuild", "skill.record"}
	case "admin":
		return append([]string{}, queueKinds...)
	default:
		return nil
	}
}

func knownStatus(s string) bool {
	for _, item := range statuses {
		if item == s {
			return true
		}
	}
	return false
}

func laneFor(role string) map[string]bool {
	switch role {
	case "discovery":
		return discoveryLane
	case "apply":
		return applyLane
	case "outreach":
		return outreachLane
	case "admin":
		all := map[string]bool{}
		for _, s := range statuses {
			all[s] = true
		}
		return all
	default:
		return map[string]bool{}
	}
}

func canPatch(role string) bool {
	return role == "discovery" || role == "apply" || role == "outreach" || role == "admin"
}

var discoveryFields = map[string]bool{
	"company": true, "title": true, "location": true, "remote": true, "url": true, "apply_url": true,
	"apply_kind": true, "ats": true, "req_id": true, "sources": true, "description": true,
	"expectations": true, "pay": true, "posted_at": true, "status": true, "score": true, "owners": true,
	"apply_packet": true, "research": true, "notes": true, "rejection": true, "conflicts": true,
}
var applyFields = map[string]bool{
	"status": true, "owners": true, "proof": true, "outreach_packet": true, "notes": true, "rejection": true,
}
var outreachFields = map[string]bool{
	"status": true, "owners": true, "outreach_packet": true, "notes": true, "rejection": true,
}

func fieldsFor(role string) map[string]bool {
	switch role {
	case "discovery":
		return discoveryFields
	case "apply":
		return applyFields
	case "outreach":
		return outreachFields
	case "admin":
		out := map[string]bool{"stopped": true, "stop_reason": true}
		for k := range discoveryFields {
			out[k] = true
		}
		for k := range applyFields {
			out[k] = true
		}
		return out
	default:
		return map[string]bool{}
	}
}

func capabilities(role string) map[string]any {
	return map[string]any{
		"role":             role,
		"can_create":       role == "discovery" || role == "admin",
		"can_patch":        canPatch(role),
		"can_stop":         role == "admin",
		"can_delete":       role == "admin",
		"can_hygiene":      role == "admin" || role == "maintenance",
		"can_import":       role == "admin" || role == "maintenance",
		"can_export":       role == "admin" || role == "maintenance",
		"can_people":       role == "outreach" || role == "admin",
		"can_resume":       role == "apply" || role == "outreach" || role == "admin",
		"can_log_metrics":  true,
		"can_read_metrics": role == "admin" || role == "maintenance",
	}
}

func mustJSON(v any) json.RawMessage {
	b, err := json.Marshal(v)
	if err != nil {
		return []byte("null")
	}
	return b
}
