package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/unownone/jobos/server/internal/blob"
	"github.com/unownone/jobos/server/internal/cache"
	"github.com/unownone/jobos/server/internal/config"
	"github.com/unownone/jobos/server/internal/httpapi"
	"github.com/unownone/jobos/server/internal/realtime"
	"github.com/unownone/jobos/server/internal/store"
	"github.com/unownone/jobos/server/internal/telemetry"
)

func main() {
	log := telemetry.Init(telemetry.Options{})
	defer func() { _ = telemetry.Shutdown(context.Background()) }()

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
			log.Error("store open failed", "error.message", err.Error())
			os.Exit(1)
		}
		log.Warn("store open retrying", "error.message", err.Error())
		time.Sleep(time.Second)
	}
	defer db.Close()

	blobs, err := blob.Open(blob.Settings{
		Driver: cfg.BlobDriver, Root: cfg.BlobRoot, Endpoint: cfg.S3Endpoint, Region: cfg.S3Region,
		Bucket: cfg.S3Bucket, AccessKey: cfg.S3AccessKey, SecretKey: cfg.S3SecretKey, UsePathStyle: cfg.S3UsePathStyle,
	})
	if err != nil {
		log.Error("blob open failed", "error.message", err.Error())
		os.Exit(1)
	}
	if ready, ok := blobs.(interface{ EnsureBucket(context.Context) error }); ok {
		if err := ready.EnsureBucket(ctx); err != nil {
			log.Error("blob bucket failed", "error.message", err.Error())
			os.Exit(1)
		}
	}
	hot, err := cache.Open(cfg.RedisURL, os.Getenv("CACHE_DRIVER"))
	if err != nil {
		log.Error("cache open failed", "error.message", err.Error())
		os.Exit(1)
	}
	rt := realtime.New()
	srv := httpapi.New(cfg, db, blobs, hot, rt)
	seeded := srv.Seed(ctx)
	log.Info("hub listening",
		"server.address", cfg.Addr,
		"store", db.Name(),
		"cache", hot.Name(),
		"blob", blobs.Name(),
		"seeded_skills", seeded,
		"otel.service.name", telemetry.ServiceName(),
		"otel.logs.exporter", first(os.Getenv("OTEL_LOGS_EXPORTER"), "console"),
	)

	httpSrv := &http.Server{Addr: cfg.Addr, Handler: srv.Router()}
	go func() {
		if err := httpSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("http server stopped", "error.message", err.Error())
			os.Exit(1)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()
	log.Info("hub shutting down")
	if err := httpSrv.Shutdown(shutdownCtx); err != nil {
		log.Warn("hub graceful shutdown incomplete", "error.message", err.Error())
		_ = httpSrv.Close()
	}
}

func first(v, fallback string) string {
	if v == "" {
		return fallback
	}
	return v
}
