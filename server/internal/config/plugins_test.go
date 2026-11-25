package config

import "testing"

func TestPluginsStayOffUntilHostsExist(t *testing.T) {
	cfg := Config{BlobDriver: "memory", S3Bucket: "jobos"}
	cfg.applyPlugins(func(string) string { return "" }, func(string) bool { return true })
	if cfg.DatabaseURL != "" || cfg.RedisURL != "" || cfg.BlobDriver != "memory" {
		t.Fatalf("plugins ran without HUB_PLUGINS: %#v", cfg)
	}
	env := map[string]string{"HUB_PLUGINS": "auto", "JOBOS_PG_PASSWORD": "s3cret"}
	up := map[string]bool{"postgres": true}
	cfg.applyPlugins(func(key string) string { return env[key] }, func(name string) bool { return up[name] })
	if cfg.DatabaseURL != "postgres://jobos:s3cret@postgres:5432/jobos?sslmode=disable" {
		t.Fatalf("database url %s", cfg.DatabaseURL)
	}
	env["JOBOS_PG_HOST"] = "db"
	env["JOBOS_PG_PORT"] = "5433"
	up["db"] = true
	cfg.DatabaseURL = ""
	cfg.applyPlugins(func(key string) string { return env[key] }, func(name string) bool { return up[name] })
	if cfg.DatabaseURL != "postgres://jobos:s3cret@db:5433/jobos?sslmode=disable" {
		t.Fatalf("host/port database url %s", cfg.DatabaseURL)
	}
	env["JOBOS_PG_HOST"] = "::1"
	up["::1"] = true
	cfg.DatabaseURL = ""
	cfg.applyPlugins(func(key string) string { return env[key] }, func(name string) bool { return up[name] })
	if cfg.DatabaseURL != "postgres://jobos:s3cret@[::1]:5433/jobos?sslmode=disable" {
		t.Fatalf("ipv6 database url %s", cfg.DatabaseURL)
	}
	if cfg.RedisURL != "" || cfg.BlobDriver != "memory" {
		t.Fatalf("unrelated drivers changed: %#v", cfg)
	}
	env["DATABASE_URL"] = "postgres://explicit/jobos"
	env["BLOB_DRIVER"] = "filesystem"
	up["redis"] = true
	up["minio"] = true
	cfg.DatabaseURL = "postgres://explicit/jobos"
	cfg.applyPlugins(func(key string) string { return env[key] }, func(name string) bool { return up[name] })
	if cfg.DatabaseURL != "postgres://explicit/jobos" {
		t.Fatalf("explicit database replaced: %s", cfg.DatabaseURL)
	}
	if cfg.RedisURL != "redis://redis:6379/0" {
		t.Fatalf("redis %s", cfg.RedisURL)
	}
	if cfg.BlobDriver != "memory" {
		t.Fatalf("explicit blob driver replaced: %s", cfg.BlobDriver)
	}

	delete(env, "BLOB_DRIVER")
	cfg.BlobDriver = "filesystem"
	cfg.applyPlugins(func(key string) string { return env[key] }, func(name string) bool { return up[name] })
	if cfg.BlobDriver != "s3" {
		t.Fatalf("empty BLOB_DRIVER should let MinIO replace filesystem adapter, got %s", cfg.BlobDriver)
	}
	if cfg.S3Endpoint != "http://minio:9000" {
		t.Fatalf("s3 endpoint %s", cfg.S3Endpoint)
	}
}
