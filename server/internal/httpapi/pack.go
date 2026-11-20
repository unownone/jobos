package httpapi

import (
	"archive/zip"
	"bytes"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/unownone/jobos/server/internal/store"
)

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
		"docs/catalogs/skills-and-mcps.md", "docs/catalogs/skill-outline.md",
	},
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

func (s *Server) repoFile(rel string) (string, []byte, bool) {
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
	track := p.Track
	if track == "" {
		track = "discovery"
	}
	skills := trackSkills[track]
	if skills == nil {
		skills = []string{}
	}
	readings := trackReadings[track]
	if readings == nil {
		readings = []string{}
	}
	c.JSON(http.StatusOK, gin.H{
		"track":    track,
		"skills":   skills,
		"readings": readings,
		"pack":     "/api/packs/current/skills.zip",
	})
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
