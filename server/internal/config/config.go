// Package config loads Hub process settings. Empty URLs mean the matching
// driver stays off: memory database, no cache, in-process blobs.
package config

import (
	"os"
	"strings"
)

type Config struct {
	Addr        string
	PublicURL   string
	RepoRoot    string
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
		Addr:           env("HUB_ADDR", ":8080"),
		PublicURL:      strings.TrimRight(os.Getenv("HUB_PUBLIC_URL"), "/"),
		RepoRoot:       os.Getenv("HUB_REPO_ROOT"),
		DatabaseURL:    strings.TrimSpace(os.Getenv("DATABASE_URL")),
		RedisURL:       strings.TrimSpace(os.Getenv("REDIS_URL")),
		BlobDriver:     strings.ToLower(env("BLOB_DRIVER", "memory")),
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
	if cfg.Addr != "" && !strings.Contains(cfg.Addr, ":") {
		cfg.Addr = ":" + cfg.Addr
	}
	if port := os.Getenv("PORT"); port != "" && os.Getenv("HUB_ADDR") == "" {
		cfg.Addr = ":" + port
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
