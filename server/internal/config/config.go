// Package config loads Hub process settings. Empty URLs mean the matching
// driver stays off: memory database, no cache, in-process blobs.
package config

import (
	"os"
	"path/filepath"
	"strings"
)

type Config struct {
	Addr        string
	PublicURL   string
	RepoRoot    string
	WebRoot     string
	DatabaseURL string

	RedisURL string

	BlobDriver     string
	BlobRoot       string
	S3Endpoint     string
	S3Region       string
	S3Bucket       string
	S3AccessKey    string
	S3SecretKey    string
	S3UsePathStyle bool

	CompatTokens   map[string]string
	BootstrapToken string
}

func Load() Config {
	cfg := Config{
		Addr:           listenAddr(),
		PublicURL:      strings.TrimRight(os.Getenv("HUB_PUBLIC_URL"), "/"),
		RepoRoot:       env("HUB_REPO_ROOT", "/opt/jobos"),
		WebRoot:        webRoot(),
		DatabaseURL:    strings.TrimSpace(os.Getenv("DATABASE_URL")),
		RedisURL:       strings.TrimSpace(os.Getenv("REDIS_URL")),
		BlobDriver:     blobDriver(),
		BlobRoot:       env("BLOB_ROOT", "/tmp/jobos-blobs"),
		S3Endpoint:     strings.TrimSpace(os.Getenv("S3_ENDPOINT")),
		S3Region:       env("S3_REGION", "us-east-1"),
		S3Bucket:       env("S3_BUCKET", "jobos"),
		S3AccessKey:    os.Getenv("S3_ACCESS_KEY"),
		S3SecretKey:    os.Getenv("S3_SECRET_KEY"),
		S3UsePathStyle: env("S3_USE_PATH_STYLE", "true") != "false",
		CompatTokens:   map[string]string{},
		BootstrapToken: strings.TrimSpace(os.Getenv("HUB_BOOTSTRAP_TOKEN")),
	}
	for role, key := range map[string]string{
		"discovery":   "BOARD_TOKEN_DISCOVERY",
		"apply":       "BOARD_TOKEN_APPLY",
		"outreach":    "BOARD_TOKEN_OUTREACH",
		"admin":       "BOARD_TOKEN_ADMIN",
		"maintenance": "BOARD_TOKEN_MAINTENANCE",
	} {
		if v := strings.TrimSpace(os.Getenv(key)); v != "" {
			cfg.CompatTokens[role] = v
		}
	}
	return cfg
}

func env(key, fallback string) string {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return fallback
	}
	return v
}

// listenAddr keeps legacy BOARD_HOST/BOARD_PORT (Coolify hub compose) working.
// HUB_ADDR wins, then Railway PORT, then BOARD_*, then :8787 (root Dockerfile).
func listenAddr() string {
	if addr := strings.TrimSpace(os.Getenv("HUB_ADDR")); addr != "" {
		if !strings.Contains(addr, ":") {
			return ":" + addr
		}
		return addr
	}
	if port := strings.TrimSpace(os.Getenv("PORT")); port != "" {
		return ":" + port
	}
	if port := strings.TrimSpace(os.Getenv("BOARD_PORT")); port != "" {
		host := strings.TrimSpace(os.Getenv("BOARD_HOST"))
		if host == "" || host == "0.0.0.0" {
			return ":" + port
		}
		return host + ":" + port
	}
	return ":8787"
}

// webRoot prefers HUB_WEB_ROOT. An empty override still falls back to the image
// path so Coolify/host env wipes do not serve a bare Gin 404 for `/`.
func webRoot() string {
	if v := strings.TrimSpace(os.Getenv("HUB_WEB_ROOT")); v != "" {
		return v
	}
	fallback := "/opt/jobos/web"
	if info, err := os.Stat(filepath.Join(fallback, "index.html")); err == nil && !info.IsDir() {
		return fallback
	}
	return ""
}

// blobDriver accepts the legacy BLOB_ADAPTER name used by Coolify hub envs.
func blobDriver() string {
	if v := strings.ToLower(strings.TrimSpace(os.Getenv("BLOB_DRIVER"))); v != "" {
		return v
	}
	if v := strings.ToLower(strings.TrimSpace(os.Getenv("BLOB_ADAPTER"))); v != "" {
		return v
	}
	return "memory"
}
