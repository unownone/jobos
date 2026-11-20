package httpapi

import (
	"regexp"
	"strings"
	"time"
	"unicode"

	"github.com/unownone/jobos/server/internal/store"
)

var memoryKinds = map[string]map[string]bool{
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

var hubTracks = []string{"discovery", "application", "outreach", "maintenance"}

var secretWord = regexp.MustCompile(`(?i)\b(password|passwd|secret|cookie|api-key|apikey)\b`)

var dumpMarkers = []string{"transcript", "as an ai", "here is the full", "paste of the jd", "job description follows"}

func podScope(pod string) string {
	switch {
	case pod == "common" || strings.HasPrefix(pod, "common"):
		return "common"
	case strings.HasPrefix(pod, "track:"):
		return "track"
	default:
		return "worker"
	}
}

func resolveWritePod(p principal, raw string) (string, string) {
	text := strings.ToLower(strings.TrimSpace(raw))
	if text == "" {
		text = "worker"
	}
	switch text {
	case "common", "shared", "global":
		return "common", ""
	case "worker", "self", "me":
		return "worker:" + p.UserID, ""
	case "track", "lane":
		if p.Track == "" {
			return "", "this principal has no track pod"
		}
		return "track:" + p.Track, ""
	}
	if track := canonicalTrack(text); track != "" {
		if p.Role != "admin" && track != p.Track {
			return "", "cannot write another track's shared pod"
		}
		return "track:" + track, ""
	}
	if strings.HasPrefix(text, "worker:") {
		ident := strings.TrimSpace(raw[len("worker:"):])
		if ident == "" || ident == "self" || ident == "me" || ident == p.UserID {
			return "worker:" + p.UserID, ""
		}
		return "", "cannot write another worker's private pod"
	}
	if strings.HasPrefix(text, "track:") {
		track := canonicalTrack(raw[len("track:"):])
		if track == "" {
			return "", "unknown track pod"
		}
		if p.Role != "admin" && track != p.Track {
			return "", "cannot write another track's shared pod"
		}
		return "track:" + track, ""
	}
	return "", "pod must be worker, track, common, or track:<name>"
}

func canReadPod(p principal, pod string) bool {
	if pod == "common" || strings.HasPrefix(pod, "worker:"+p.UserID) || (p.Track != "" && pod == "track:"+p.Track) {
		return true
	}
	return p.Role == "admin" || p.Role == "maintenance"
}

func validateMemory(pod, kind, title, body string) string {
	scope := podScope(pod)
	kind = strings.ToLower(strings.TrimSpace(kind))
	if !memoryKinds[scope][kind] {
		return "kind is not allowed in this pod"
	}
	title = strings.Join(strings.Fields(title), " ")
	body = strings.TrimSpace(body)
	if len(title) < 8 || len(title) > 120 {
		return "title must be 8–120 characters"
	}
	minBody := 40
	if kind == "working_note" || kind == "reminder" {
		minBody = 24
	}
	if len(body) < minBody {
		return "body is too short"
	}
	if len(body) > 800 {
		return "body is too long"
	}
	if looksSecret(title) || looksSecret(body) {
		return "memory must not contain secrets"
	}
	if body != "" && (body[0] == '{' || body[0] == '[') {
		return "do not store JSON dumps"
	}
	if strings.Count(body, "\n") > 8 {
		return "too many lines"
	}
	lowered := strings.ToLower(title + "\n" + body)
	for _, marker := range dumpMarkers {
		if strings.Contains(lowered, marker) {
			return "that looks like a transcript or dump"
		}
	}
	return ""
}

func looksSecret(text string) bool {
	lower := strings.ToLower(text)
	for _, prefix := range []string{"jh_agt_", "jh_own_", "jh_inv_", "jh_boot_", "jh_adm_", "sk-", "xox", "api_key", "apikey", "board_token", "hub_key", "private_key", "authorization: bearer", "bearer jh_"} {
		if strings.Contains(lower, prefix) {
			return true
		}
	}
	return secretWord.MatchString(text)
}

func memoryOverCap(items []store.MemoryItem, pod string) bool {
	capN := 6
	switch podScope(pod) {
	case "track":
		capN = 3
	case "common":
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

func defaultExpiry(pod, kind, importance string) string {
	days := 0
	switch {
	case strings.HasPrefix(pod, "worker:") || kind == "working_note" || kind == "reminder":
		days = 7
	case importance == "1":
		days = 30
	}
	if days == 0 {
		return ""
	}
	return time.Now().UTC().Add(time.Duration(days) * 24 * time.Hour).Format(time.RFC3339)
}

func memoryExpired(item store.MemoryItem, at time.Time) bool {
	if item.ExpiresAt == "" || item.Pinned {
		return false
	}
	stamp, err := time.Parse(time.RFC3339, item.ExpiresAt)
	return err == nil && !stamp.After(at)
}

func memoryMatches(item store.MemoryItem, q, jobID, company, kind string) bool {
	if kind != "" && item.Kind != kind {
		return false
	}
	if jobID != "" && item.JobID != jobID {
		return false
	}
	if company != "" && !strings.EqualFold(item.Company, company) {
		return false
	}
	if q == "" {
		return true
	}
	hay := strings.ToLower(item.Title + "\n" + item.Body + "\n" + item.Company)
	for _, tok := range strings.FieldsFunc(strings.ToLower(q), func(r rune) bool {
		return !unicode.IsLetter(r) && !unicode.IsDigit(r) && r != '_'
	}) {
		if len(tok) < 2 {
			continue
		}
		if !strings.Contains(hay, tok) {
			return false
		}
	}
	return true
}

func compactBody(body string) string {
	text := strings.Join(strings.Fields(body), " ")
	if len(text) <= 240 {
		return text
	}
	return strings.TrimRight(text[:239], " ") + "…"
}
