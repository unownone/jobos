package httpapi

import (
	"archive/zip"
	"bytes"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/unownone/jobos/server/internal/store"
)

var allowedScripts = map[string]bool{
	"install_agent_skills.sh": true,
	"link_agent_skills.sh":    true,
	"setup_uv.sh":             true,
	"setup_vendor_mcps.sh":    true,
	"setup_deep_research.sh":  true,
}

var forbiddenBase = map[string]bool{
	".env": true, "tokens.local.json": true, "candidate.yaml": true, "board.db": true, "metrics.sqlite": true,
}

var catalogDate = regexp.MustCompile(`Last catalog pass[:\s\*]*(\d{4}-\d{2}-\d{2})`)

var trackSkills = map[string][]string{
	"discovery":   {"skill-and-mcp-catalog", "job-discovery", "deep-research"},
	"application": {"job-apply", "deep-research"},
	"outreach":    {"job-outreach", "deep-research"},
	"maintenance": {"skill-maintainer", "skill-and-mcp-catalog"},
}

var trackReadings = map[string][]string{
	"discovery": {
		"AGENTS.md", "docs/process.md", "docs/roles.md", "docs/job-hub/memory.md",
		"docs/catalogs/skills-and-mcps.md", "docs/catalogs/skill-outline.md", "handoffs/apply-packet.md",
	},
	"application": {
		"AGENTS.md", "docs/process.md", "docs/roles.md", "docs/job-hub/memory.md",
		"docs/catalogs/skill-outline.md", "handoffs/apply-packet.md",
	},
	"outreach": {
		"AGENTS.md", "docs/process.md", "docs/roles.md", "docs/job-hub/memory.md",
		"docs/catalogs/skill-outline.md", "handoffs/outreach-packet.md",
	},
	"maintenance": {
		"AGENTS.md", "docs/process.md", "docs/roles.md", "docs/job-hub/memory.md",
		"docs/catalogs/skills-and-mcps.md", "docs/catalogs/skill-outline.md", "skills/lists/INDEX.md",
	},
}

var trackProcess = map[string]gin.H{
	"discovery": {
		"must_read":        []string{"process.md#discovery-cycle", "roles.md#discovery-owner"},
		"forbidden":        []string{"Easy Apply", "form submit", "send outreach", "invent candidate"},
		"channels_default": []string{"email", "linkedin_dm"}, "catalog_first": true,
	},
	"application": {
		"must_read":        []string{"process.md#apply-cycle", "roles.md#apply-owner"},
		"forbidden":        []string{"invent jobs", "cold outreach", "skip packet"},
		"channels_default": []string{"email", "linkedin_dm"}, "catalog_first": false,
	},
	"outreach": {
		"must_read":        []string{"process.md#outreach-cycle", "roles.md#outreach-owner"},
		"forbidden":        []string{"SMS", "WhatsApp", "InMail sequences", "apply", "attach nothing"},
		"channels_default": []string{"email", "linkedin_dm"}, "catalog_first": false,
	},
	"maintenance": {
		"must_read":        []string{"roles.md#maintainer", "process.md#catalog-pass"},
		"forbidden":        []string{"discover jobs", "Easy Apply", "submit applications", "send outreach", "put secrets in lists or git"},
		"channels_default": []string{"email", "linkedin_dm"}, "catalog_first": true,
	},
}

var trackQueues = map[string][]string{
	"discovery": {"discovery.search"}, "application": {"apply.ready"},
	"outreach": {"outreach.ready"}, "maintenance": {"skill.record", "catalog.refresh"},
}

func skillAllowed(track, name string, unrestricted bool) bool {
	if name == "" || strings.Contains(name, "..") || strings.Contains(name, "/") {
		return false
	}
	if unrestricted {
		return true
	}
	for _, item := range trackSkills[track] {
		if item == name {
			return true
		}
	}
	return false
}

func allowlisted(rel string) bool {
	rel = strings.TrimPrefix(filepath.ToSlash(rel), "/")
	base := filepath.Base(rel)
	if forbiddenBase[base] || strings.HasSuffix(base, ".env") {
		return false
	}
	switch rel {
	case "AGENTS.md", "skills-lock.json", "mcp/mcp.example.json":
		return true
	}
	switch {
	case strings.HasPrefix(rel, "docs/") && !strings.HasSuffix(rel, "/"):
		return true
	case strings.HasPrefix(rel, "handoffs/") && !strings.HasSuffix(rel, "/"):
		return true
	case strings.HasPrefix(rel, "skills/") && !strings.HasSuffix(rel, "/"):
		return true
	case strings.HasPrefix(rel, "mcp/hosted/") && strings.HasSuffix(rel, ".json") && !strings.Contains(base, ".."):
		return true
	case strings.HasPrefix(rel, "scripts/") && strings.Count(rel, "/") == 1 && allowedScripts[base]:
		return true
	default:
		return false
	}
}

func (s *Server) repoFile(rel string) (string, []byte, bool) {
	if !allowlisted(rel) {
		return "", nil, false
	}
	root := s.Cfg.RepoRoot
	if root == "" {
		return "", nil, false
	}
	clean := filepath.Clean(rel)
	if clean == "." || strings.HasPrefix(clean, "..") || filepath.IsAbs(clean) {
		return "", nil, false
	}
	full := filepath.Join(root, clean)
	relToRoot, err := filepath.Rel(root, full)
	if err != nil || strings.HasPrefix(relToRoot, "..") {
		return "", nil, false
	}
	body, err := os.ReadFile(full)
	if err != nil {
		return "", nil, false
	}
	return full, body, true
}

func mediaFor(name string) string {
	switch strings.ToLower(filepath.Ext(name)) {
	case ".md":
		return "text/markdown; charset=utf-8"
	case ".json":
		return "application/json; charset=utf-8"
	case ".sh":
		return "text/x-shellscript; charset=utf-8"
	case ".yaml", ".yml":
		return "text/yaml; charset=utf-8"
	case ".txt":
		return "text/plain; charset=utf-8"
	default:
		return "application/octet-stream"
	}
}

func (s *Server) onboarding(c *gin.Context) {
	p := principalFrom(c)
	track := canonicalTrack(p.Track)
	if track == "" {
		track = "discovery"
	}
	readings := []gin.H{}
	for _, rel := range trackReadings[track] {
		_, body, ok := s.repoFile(rel)
		digest := ""
		if ok {
			digest = hash(string(body))
		}
		readings = append(readings, gin.H{"path": rel, "url": "/api/docs/" + rel, "sha256": digest})
	}
	skills := []gin.H{}
	for _, name := range trackSkills[track] {
		_, body, ok := s.repoFile("skills/" + name + "/SKILL.md")
		if !ok {
			continue
		}
		files := []string{"/api/skills/" + name + "/SKILL.md"}
		dir := filepath.Join(s.Cfg.RepoRoot, "skills", name)
		_ = filepath.Walk(dir, func(path string, info os.FileInfo, err error) error {
			if err != nil || info.IsDir() || info.Name() == "SKILL.md" {
				return nil
			}
			rel, err := filepath.Rel(dir, path)
			if err != nil {
				return nil
			}
			files = append(files, "/api/skills/"+name+"/"+filepath.ToSlash(rel))
			return nil
		})
		skills = append(skills, gin.H{"name": name, "files": files, "sha256": hash(string(body))})
	}
	var scripts []gin.H
	for name := range allowedScripts {
		if _, _, ok := s.repoFile("scripts/" + name); ok {
			scripts = append(scripts, gin.H{"name": name, "url": "/api/scripts/" + name})
		}
	}
	if scripts == nil {
		scripts = []gin.H{}
	}
	resumeURL := any(nil)
	if _, err := s.Blobs.Get(c.Request.Context(), p.AccountID, resumeKey); err == nil {
		resumeURL = "/api/candidate/resume"
	}
	source := "missing"
	if s.onboarded(c, p.AccountID) {
		source = "blob"
	}
	c.JSON(http.StatusOK, gin.H{
		"hub": gin.H{
			"public_url": s.publicURL(c), "version": "1",
			"git_sha": gitSHA(s.Cfg.RepoRoot), "built_at": now(),
		},
		"track": track, "process": trackProcess[track], "readings": readings, "skills": skills,
		"skills_zip": "/api/packs/current/skills.zip", "mcp_example": "/api/mcp/example.json",
		"scripts": scripts, "connectors_needed": connectorsFor(track),
		"heartbeat_s": 10, "stale_after_s": 300,
		"memory": gin.H{
			"recall": "/api/memory/recall", "write": "/api/memory/items",
			"move": "/api/memory/items/{id}/move", "solidify": "/api/memory/items/{id}/solidify",
			"pods": "/api/memory/pods", "docs": "/api/docs/docs/job-hub/memory.md",
			"use_every_round": true, "store_sparingly": true,
		},
		"queues":             trackQueues[track],
		"candidate":          gin.H{"present": source == "blob", "source": source, "resume_url": resumeURL},
		"catalog_updated_at": catalogUpdated(s.Cfg.RepoRoot),
		"registry":           "/api/registry/skills", "mcp_registry": "/api/registry/mcps",
	})
}

func connectorsFor(track string) []gin.H {
	type row struct {
		id, reason, auth, env, hosted string
		need                          []string
	}
	rows := []row{
		{"gmail", "Outreach drafts with resume PDF attachments (Gmail MCP).", "https://gmailmcp.googleapis.com/mcp/v1", "GMAIL_*", "/api/mcp/hosted/google-workspace.json", []string{"outreach"}},
		{"google_drive", "Optional Drive access for resume/docs the Hub does not store in YAML.", "https://drivemcp.googleapis.com/mcp/v1", "GOOGLE_DRIVE_*", "/api/mcp/hosted/google-workspace.json", nil},
		{"google_calendar", "Optional interview scheduling; never a Hub login.", "https://calendarmcp.googleapis.com/mcp/v1", "GOOGLE_CALENDAR_*", "/api/mcp/hosted/google-workspace.json", []string{"outreach"}},
		{"indeed", "Discovery search via official Indeed MCP when the operator has OAuth.", "https://mcp.indeed.com/claude/mcp", "INDEED_*", "/api/mcp/hosted/indeed.json", []string{"discovery"}},
		{"exa", "Deep research / web fetch. Agent local env key; Hub never returns the value.", "https://mcp.exa.ai/mcp", "EXA_API_KEY", "/api/mcp/hosted/exa.json", []string{"discovery", "application", "outreach", "maintenance"}},
	}
	out := make([]gin.H, 0, len(rows))
	for _, item := range rows {
		required := false
		for _, need := range item.need {
			if need == track {
				required = true
			}
		}
		out = append(out, gin.H{
			"id": item.id, "required": required, "reason": item.reason,
			"auth_url": item.auth, "env_fallback": item.env, "hosted": item.hosted,
		})
	}
	return out
}

func gitSHA(root string) string {
	if root == "" {
		return ""
	}
	out, err := exec.Command("git", "-C", root, "rev-parse", "HEAD").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

func catalogUpdated(root string) string {
	body, err := os.ReadFile(filepath.Join(root, "docs", "catalogs", "skills-and-mcps.md"))
	if err != nil {
		return ""
	}
	match := catalogDate.FindSubmatch(body)
	if match == nil {
		return ""
	}
	return string(match[1])
}

func (s *Server) getDoc(c *gin.Context) {
	p := principalFrom(c)
	rel := strings.TrimPrefix(c.Param("path"), "/")
	if strings.HasPrefix(rel, "skills/") && p.Role != "admin" && p.Role != "maintenance" {
		parts := strings.Split(rel, "/")
		if len(parts) < 2 || !skillAllowed(p.Track, parts[1], false) {
			fail(c, 404, "not found")
			return
		}
	}
	s.sendRepo(c, rel)
}

func (s *Server) getSkillFile(c *gin.Context) {
	p := principalFrom(c)
	name := c.Param("name")
	file := strings.TrimPrefix(c.Param("file"), "/")
	unrestricted := p.Role == "admin" || p.Role == "maintenance"
	if !skillAllowed(p.Track, name, unrestricted) {
		fail(c, 404, "not found")
		return
	}
	s.sendRepo(c, "skills/"+name+"/"+file)
}

func (s *Server) sendRepo(c *gin.Context, rel string) {
	full, body, ok := s.repoFile(rel)
	if !ok {
		fail(c, 404, "not found")
		return
	}
	info, err := os.Stat(full)
	if err != nil || info.IsDir() {
		fail(c, 404, "not found")
		return
	}
	c.Data(http.StatusOK, mediaFor(full), body)
}

func (s *Server) skillsZip(c *gin.Context) {
	p := principalFrom(c)
	track := p.Track
	if track == "" {
		track = "discovery"
	}
	names := trackSkills[track]
	if p.Role == "admin" || p.Role == "maintenance" {
		seen := map[string]bool{}
		names = nil
		for _, list := range trackSkills {
			for _, name := range list {
				if !seen[name] {
					seen[name] = true
					names = append(names, name)
				}
			}
		}
	}
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	root := s.Cfg.RepoRoot
	if root == "" {
		fail(c, 404, "pack zip not found")
		return
	}
	for _, name := range names {
		dir := filepath.Join(root, "skills", name)
		_ = filepath.Walk(dir, func(path string, info os.FileInfo, err error) error {
			if err != nil || info.IsDir() {
				return nil
			}
			rel, err := filepath.Rel(filepath.Join(root, "skills"), path)
			if err != nil {
				return nil
			}
			w, err := zw.Create(filepath.ToSlash(rel))
			if err != nil {
				return nil
			}
			f, err := os.Open(path)
			if err != nil {
				return nil
			}
			_, _ = io.Copy(w, f)
			_ = f.Close()
			return nil
		})
	}
	if err := zw.Close(); err != nil {
		fail(c, 500, err.Error())
		return
	}
	c.Header("Content-Disposition", `attachment; filename="skills-`+track+`.zip"`)
	c.Data(http.StatusOK, "application/zip", buf.Bytes())
}

func (s *Server) rebuildPack(c *gin.Context) {
	p := principalFrom(c)
	if p.Role != "admin" && p.Role != "maintenance" {
		fail(c, 403, "maintainer only")
		return
	}
	n := s.Seed(c.Request.Context())
	_, _ = s.DB.AddEvent(c.Request.Context(), store.Event{AccountID: p.AccountID, TS: now(), ActorRole: p.Role, Actor: p.Actor, Action: "pack_rebuild"})
	c.JSON(http.StatusOK, gin.H{"ok": true, "seeded": n})
}
