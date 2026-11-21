package config

import (
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
