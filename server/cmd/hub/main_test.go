package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestHubMigrateRequiresDatabaseURL(t *testing.T) {
	exe := buildHub(t)
	cmd := exec.Command(exe, "migrate")
	cmd.Env = append(os.Environ(), "DATABASE_URL=", "HUB_PLUGINS=off")
	out, err := cmd.CombinedOutput()
	if err == nil {
		t.Fatalf("expected failure, got ok: %s", out)
	}
	if !strings.Contains(string(out), "DATABASE_URL") {
		t.Fatalf("expected DATABASE_URL error, got: %s", out)
	}
}

func TestHubHelp(t *testing.T) {
	exe := buildHub(t)
	cmd := exec.Command(exe, "help")
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("help: %v\n%s", err, out)
	}
	if !strings.Contains(string(out), "hub migrate") {
		t.Fatalf("help missing migrate: %s", out)
	}
}

func buildHub(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	exe := filepath.Join(dir, "hub")
	cmd := exec.Command("go", "build", "-o", exe, ".")
	cmd.Dir = "."
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("build hub: %v\n%s", err, out)
	}
	return exe
}
