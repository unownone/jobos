package config

import (
	"context"
	"net"
	"net/url"
	"os"
	"strings"
	"time"
)

// Plug fills empty driver URLs when HUB_PLUGINS=auto and the compose hostnames
// resolve. A plain `docker compose up` leaves them unset. Adding --profile data,
// cache, or blobs puts postgres, redis, or minio on the network and the API
// picks that driver up.
func (c *Config) Plug() {
	c.applyPlugins(func(key string) string {
		return strings.TrimSpace(osGetenv(key))
	}, hostResolves)
}

func (c *Config) applyPlugins(getenv func(string) string, up func(string) bool) {
	if !strings.EqualFold(getenv("HUB_PLUGINS"), "auto") {
		return
	}
	if getenv("DATABASE_URL") == "" {
		host := first(getenv("JOBOS_PG_HOST"), "postgres")
		if up(host) {
			user := first(getenv("JOBOS_PG_USER"), "jobos")
			pass := first(getenv("JOBOS_PG_PASSWORD"), "jobos")
			name := first(getenv("JOBOS_PG_DB"), "jobos")
			port := first(getenv("JOBOS_PG_PORT"), "5432")
			c.DatabaseURL = "postgres://" + url.QueryEscape(user) + ":" + url.QueryEscape(pass) + "@" + net.JoinHostPort(host, port) + "/" + url.PathEscape(name) + "?sslmode=disable"
		}
	}
	if getenv("REDIS_URL") == "" && up("redis") {
		c.RedisURL = "redis://redis:6379/0"
	}
	// Empty BLOB_DRIVER lets MinIO win even when legacy BLOB_ADAPTER=filesystem
	// was loaded first. Set BLOB_DRIVER=filesystem explicitly to keep the volume.
	if getenv("BLOB_DRIVER") == "" && up("minio") {
		c.BlobDriver = "s3"
		if getenv("S3_ENDPOINT") == "" {
			c.S3Endpoint = "http://minio:9000"
		}
		if getenv("S3_ACCESS_KEY") == "" {
			c.S3AccessKey = "jobos"
		}
		if getenv("S3_SECRET_KEY") == "" {
			c.S3SecretKey = "jobossecret"
		}
		if c.S3Bucket == "" {
			c.S3Bucket = "jobos"
		}
		c.S3UsePathStyle = true
	}
}

func first(value, fallback string) string {
	if strings.TrimSpace(value) == "" {
		return fallback
	}
	return strings.TrimSpace(value)
}

func hostResolves(name string) bool {
	ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()
	addrs, err := net.DefaultResolver.LookupHost(ctx, name)
	return err == nil && len(addrs) > 0
}

// osGetenv is a var so tests can avoid the process environment. Plug uses it.
var osGetenv = os.Getenv
