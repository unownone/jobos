package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLegacyBoardPortAndBlobAdapter(t *testing.T) {
	t.Setenv("HUB_ADDR", "")
	t.Setenv("PORT", "")
	t.Setenv("BOARD_HOST", "0.0.0.0")
	t.Setenv("BOARD_PORT", "8787")
	t.Setenv("BLOB_DRIVER", "")
	t.Setenv("BLOB_ADAPTER", "filesystem")
	cfg := Load()
	if cfg.Addr != ":8787" {
		t.Fatalf("addr %q", cfg.Addr)
	}
	if cfg.BlobDriver != "filesystem" {
		t.Fatalf("blob %q", cfg.BlobDriver)
	}
	t.Setenv("HUB_ADDR", ":9090")
	cfg = Load()
	if cfg.Addr != ":9090" {
		t.Fatalf("HUB_ADDR should win, got %q", cfg.Addr)
	}
}

func TestDefaultListenAddrIsLegacyHubPort(t *testing.T) {
	t.Setenv("HUB_ADDR", "")
	t.Setenv("PORT", "")
	t.Setenv("BOARD_PORT", "")
	t.Setenv("BOARD_HOST", "")
	cfg := Load()
	if cfg.Addr != ":8787" {
		t.Fatalf("default addr %q", cfg.Addr)
	}
}

func TestDockerfileServesSPAOnLegacyPort(t *testing.T) {
	root := repoRoot(t)
	raw, err := os.ReadFile(filepath.Join(root, "Dockerfile"))
	if err != nil {
		t.Fatal(err)
	}
	text := string(raw)
	for _, needle := range []string{
		"HUB_WEB_ROOT=/opt/jobos/web",
		"BOARD_PORT=8787",
		"EXPOSE 8787",
		"npm ci",
		"COPY --from=web /src/dist /opt/jobos/web",
		"hub-healthcheck",
	} {
		if !strings.Contains(text, needle) {
			t.Fatalf("Dockerfile missing %q", needle)
		}
	}
	if strings.Contains(text, "EXPOSE 8080") {
		t.Fatalf("root Dockerfile must not advertise 8080; Coolify/host publish 8787")
	}
	compose, err := os.ReadFile(filepath.Join(root, "docker-compose.yml"))
	if err != nil {
		t.Fatal(err)
	}
	for _, needle := range []string{`HUB_WEB_ROOT: "/opt/jobos/web"`, `HUB_REPO_ROOT: "/opt/jobos"`} {
		if !strings.Contains(string(compose), needle) {
			t.Fatalf("compose missing %s", needle)
		}
	}
}
