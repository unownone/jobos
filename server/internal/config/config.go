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
		PublicURL:      publicURLFromEnv(),
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

// publicURLFromEnv prefers HUB_PUBLIC_URL. Coolify / compose often set only
// HUB_PUBLIC_HOST (hostname or host:port); turn that into an absolute origin so
// invite join links are shareable outside the Cloud Run *.run.app hostname.
//
// Scheme rules (invite join_url must be pasteable by agents):
//   - explicit http(s):// in HUB_PUBLIC_HOST wins
//   - :443 → https, :80 or any other host:port → http
//   - bare localhost / loopback / IP → http
//   - bare DNS name (ikr.one) → https (prod default when operators omit the scheme)
func publicURLFromEnv() string {
	if v := strings.TrimRight(strings.TrimSpace(os.Getenv("HUB_PUBLIC_URL")), "/"); v != "" {
		return v
	}
	host := strings.TrimSpace(os.Getenv("HUB_PUBLIC_HOST"))
	if host == "" {
		return ""
	}
	host = strings.TrimRight(host, "/")
	if strings.HasPrefix(host, "http://") || strings.HasPrefix(host, "https://") {
		return strings.TrimRight(host, "/")
	}
	scheme := "https"
	switch {
	case strings.HasSuffix(host, ":80"):
		host = strings.TrimSuffix(host, ":80")
		scheme = "http"
	case strings.HasSuffix(host, ":443"):
		host = strings.TrimSuffix(host, ":443")
		scheme = "https"
	case strings.Contains(host, ":"):
		// 127.0.0.1:8787 / board-style local binds stay http.
		// Bracketed IPv6 with a port also lands here.
		scheme = "http"
	case isLoopbackOrIP(host):
		scheme = "http"
	}
	return scheme + "://" + host
}

func isLoopbackOrIP(host string) bool {
	h := strings.Trim(host, "[]")
	switch strings.ToLower(h) {
	case "localhost", "127.0.0.1", "::1", "0.0.0.0":
		return true
	}
	// Digits-and-dots IPv4, or any remaining colon → treat as IP (http).
	if strings.Count(h, ".") == 3 {
		ok := true
		for _, p := range strings.Split(h, ".") {
			if p == "" {
				ok = false
				break
			}
			for _, c := range p {
				if c < '0' || c > '9' {
					ok = false
					break
				}
			}
			if !ok {
				break
			}
		}
		if ok {
			return true
		}
	}
	return strings.Contains(h, ":")
}
