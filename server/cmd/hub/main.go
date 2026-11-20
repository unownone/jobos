package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/unownone/jobos/server/internal/blob"
	"github.com/unownone/jobos/server/internal/cache"
	"github.com/unownone/jobos/server/internal/config"
	"github.com/unownone/jobos/server/internal/httpapi"
	"github.com/unownone/jobos/server/internal/realtime"
	"github.com/unownone/jobos/server/internal/store"
)

func main() {
	cfg := config.Load()
	cfg.Plug()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	var db store.Store
	var err error
	for {
		db, err = store.Open(ctx, cfg.DatabaseURL)
		if err == nil || cfg.DatabaseURL == "" {
			break
		}
		if ctx.Err() != nil {
			log.Fatalf("store: %v", err)
		}
		log.Printf("store: %v; retrying", err)
		time.Sleep(time.Second)
	}
	defer db.Close()

	blobs, err := blob.Open(blob.Settings{
		Driver: cfg.BlobDriver, Root: cfg.BlobRoot, Endpoint: cfg.S3Endpoint, Region: cfg.S3Region,
		Bucket: cfg.S3Bucket, AccessKey: cfg.S3AccessKey, SecretKey: cfg.S3SecretKey, UsePathStyle: cfg.S3UsePathStyle,
	})
	if err != nil {
		log.Fatalf("blob: %v", err)
	}
	if ready, ok := blobs.(interface{ EnsureBucket(context.Context) error }); ok {
		if err := ready.EnsureBucket(ctx); err != nil {
			log.Fatalf("blob bucket: %v", err)
		}
	}
	hot, err := cache.Open(cfg.RedisURL, os.Getenv("CACHE_DRIVER"))
	if err != nil {
		log.Fatalf("cache: %v", err)
	}
	rt := realtime.New()
	srv := httpapi.New(cfg, db, blobs, hot, rt)
	seeded := srv.Seed(ctx)
	log.Printf("jobos hub listening on %s store=%s cache=%s blob=%s seeded_skills=%d", cfg.Addr, db.Name(), hot.Name(), blobs.Name(), seeded)
	if err := http.ListenAndServe(cfg.Addr, srv.Router()); err != nil {
		log.Fatal(err)
	}
}
