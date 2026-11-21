package agentflow

import (
	"crypto/sha256"
	"encoding/base64"
	"net/url"
	"regexp"
	"strings"
)

const (
	LaneFind     = "find"
	LaneApply    = "apply"
	LaneOutreach = "outreach"
	FindCap      = 12
)

var (
	laneNeeds = map[string][]string{
		LaneFind:     {"browser"},
		LaneApply:    {"browser"},
		LaneOutreach: {"email"},
	}
	laneSkill = map[string]string{
		LaneFind:     "job-discovery",
		LaneApply:    "job-apply",
		LaneOutreach: "job-outreach",
	}
	pkceVerifier = regexp.MustCompile(`^[A-Za-z0-9._~-]{43,128}$`)
)

type Capabilities struct {
	Browser  bool `json:"browser"`
	Email    bool `json:"email"`
	Reported bool `json:"reported"`
}

type SessionView struct {
	Lanes        []string
	Capabilities Capabilities
}

type JobView struct {
	ID       string
	Status   string
	Stopped  bool
	Sources  []string
	Company  string
	Title    string
}

func NormalizeLane(raw string) string {
	key := strings.ReplaceAll(strings.ReplaceAll(strings.ToLower(strings.TrimSpace(raw)), " ", "_"), "-", "_")
	switch key {
	case "find", "discovery", "source":
		return LaneFind
	case "apply", "application":
		return LaneApply
	case "outreach":
		return LaneOutreach
	default:
		return ""
	}
}

func EvaluateLane(session SessionView, lane string) map[string]any {
	canonical := NormalizeLane(lane)
	lanes := session.Lanes
	if lanes == nil {
		lanes = []string{}
	}
	caps := session.Capabilities
	if canonical == "" {
		return map[string]any{
			"can": false, "lane": lane, "reason": "unknown_lane", "missing": []string{}, "lanes": lanes,
			"instruction": "Lanes are find, apply, and outreach. Ask the human which of those this session should run.",
		}
	}
	if len(lanes) == 0 {
		return map[string]any{
			"can": false, "lane": canonical, "reason": "lanes_unset", "missing": []string{"session_lanes"}, "lanes": []string{},
			"instruction": "Ask the human which lanes this session should run: find, apply, outreach. They may pick more than one. Then call set_session_lanes. Do not pick for them.",
		}
	}
	if !contains(lanes, canonical) {
		return map[string]any{
			"can": false, "lane": canonical, "reason": "lane_not_in_session", "missing": []string{"session_lanes"}, "lanes": lanes,
			"instruction": "This session is running " + strings.Join(lanes, ", ") + ". Ask the human before adding " + canonical + ", then call set_session_lanes with the full set.",
		}
	}
	needs := laneNeeds[canonical]
	if !caps.Reported {
		return map[string]any{
			"can": false, "lane": canonical, "reason": "capabilities_not_reported", "missing": needs, "lanes": lanes,
			"instruction": "Call report_capabilities with the truth for this client. browser is true only when you can drive a real browser. email is true only when a mailbox is connected. Then call evaluate_lane again.",
		}
	}
	var missing []string
	for _, need := range needs {
		if need == "browser" && !caps.Browser || need == "email" && !caps.Email {
			missing = append(missing, need)
		}
	}
	if len(missing) > 0 {
		hints := map[string]string{
			"browser": "Find and apply need a browser in this client. Say so to the human and stop this lane.",
			"email":   "Outreach needs a connected mailbox. Say so to the human and stop this lane.",
		}
		parts := make([]string, 0, len(missing))
		for _, item := range missing {
			parts = append(parts, hints[item])
		}
		return map[string]any{
			"can": false, "lane": canonical, "reason": "missing_" + strings.Join(missing, "_"), "missing": missing, "lanes": lanes,
			"capabilities": caps, "instruction": strings.Join(parts, " "),
		}
	}
	return map[string]any{
		"can": true, "lane": canonical, "reason": "ready", "missing": []string{}, "lanes": lanes,
		"capabilities": caps, "skill": laneSkill[canonical],
		"instruction": "You can run " + canonical + ". Read " + laneSkill[canonical] + " and start_loop if you have not already.",
	}
}

func PlanLoop(lane, id string, jobs []JobView) map[string]any {
	var open []JobView
	for _, job := range jobs {
		if !job.Stopped {
			open = append(open, job)
		}
	}
	switch lane {
	case LaneFind:
		var shortlist []JobView
		var sources []string
		seen := map[string]bool{}
		for _, job := range open {
			if job.Status == "shortlisted" || job.Status == "apply_ready" {
				shortlist = append(shortlist, job)
			}
			for _, source := range job.Sources {
				if source != "" && !seen[source] {
					seen[source] = true
					sources = append(sources, source)
				}
			}
		}
		if len(shortlist) >= FindCap {
			return map[string]any{
				"status": "done", "continue": false, "lane": lane, "shortlist_count": len(shortlist), "shortlist_cap": FindCap,
				"instruction": "Shortlist is at the cap. Stop this find loop. Tell the human the ids and scores. Do not Easy Apply.",
			}
		}
		if len(sources) > 40 {
			sources = sources[:40]
		}
		return map[string]any{
			"status": "running", "continue": true, "lane": lane, "shortlist_count": len(shortlist), "shortlist_cap": FindCap,
			"sources_already_seen": sources,
			"instruction":          "Search the next source you have not covered. Dedup, then create_job. Score and write an apply packet for anything you shortlist. Do not submit an application. When that source is done, call next_loop again.",
		}
	case LaneApply:
		var pending []JobView
		for _, job := range open {
			if job.Status == "apply_ready" || job.Status == "applying" {
				pending = append(pending, job)
			}
		}
		if len(pending) == 0 {
			return map[string]any{"status": "blocked", "continue": false, "lane": lane, "instruction": "No apply_ready job. Tell the human. If find is also in this session, start_loop on find."}
		}
		job := pending[0]
		return map[string]any{
			"status": "running", "continue": true, "lane": lane, "job_id": job.ID, "company": job.Company, "title": job.Title,
			"instruction": "Open " + job.ID + " with get_job. Follow its apply packet in the browser. Then update_job with proof and status applied, and call next_loop.",
		}
	default:
		var pending []JobView
		for _, job := range open {
			if job.Status == "outreach_ready" {
				pending = append(pending, job)
			}
		}
		if len(pending) == 0 {
			for _, job := range open {
				if job.Status == "applied" {
					pending = append(pending, job)
				}
			}
		}
		if len(pending) == 0 {
			return map[string]any{"status": "blocked", "continue": false, "lane": lane, "instruction": "Nothing is ready for outreach. Tell the human. Do not invent a contact."}
		}
		job := pending[0]
		return map[string]any{
			"status": "running", "continue": true, "lane": lane, "job_id": job.ID, "company": job.Company, "title": job.Title,
			"instruction": "Read the outreach skill. Email for " + job.ID + " with the resume PDF attached, or a short LinkedIn note that asks for a chat. No SMS. Record the touch with update_job, then call next_loop.",
		}
	}
}

func RedirectURIAllowed(uri string) bool {
	text := strings.TrimSpace(uri)
	if text == "" || len(text) > 500 || strings.ContainsAny(text, "\n\r ") {
		return false
	}
	parsed, err := url.Parse(text)
	if err != nil || parsed.Fragment != "" {
		return false
	}
	host := strings.ToLower(parsed.Hostname())
	switch parsed.Scheme {
	case "javascript", "data", "file", "vbscript":
		return false
	case "https":
		return host != ""
	case "http":
		return host == "127.0.0.1" || host == "localhost" || host == "::1"
	default:
		return parsed.Scheme != "" && (parsed.Host != "" || parsed.Path != "")
	}
}

func PKCEVerifierOK(verifier string) bool {
	return pkceVerifier.MatchString(verifier)
}

func PKCSES256(verifier string) string {
	sum := sha256.Sum256([]byte(verifier))
	return strings.TrimRight(base64.URLEncoding.EncodeToString(sum[:]), "=")
}

func WithQuery(uri string, extra map[string]string) string {
	parsed, err := url.Parse(uri)
	if err != nil {
		return uri
	}
	q := parsed.Query()
	for key, value := range extra {
		q.Set(key, value)
	}
	parsed.RawQuery = q.Encode()
	return parsed.String()
}

func contains(items []string, want string) bool {
	for _, item := range items {
		if item == want {
			return true
		}
	}
	return false
}
