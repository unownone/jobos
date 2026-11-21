package telemetry

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

func TestConsoleHandlerSeverity(t *testing.T) {
	var buf bytes.Buffer
	log := Init(Options{ServiceName: "jobos-hub-test", Exporter: "console", Writer: &buf, MinLevel: slog.LevelDebug})
	log.Info("booted")
	log.Warn("auth failed", "http.status_code", 401)
	log.Error("db down", "error.message", "connection refused")

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 3 {
		t.Fatalf("want 3 lines, got %d: %s", len(lines), buf.String())
	}
	want := []string{"INFO", "WARN", "ERROR"}
	for i, line := range lines {
		var rec map[string]any
		if err := json.Unmarshal([]byte(line), &rec); err != nil {
			t.Fatalf("line %d: %v (%s)", i, err, line)
		}
		if rec["SeverityText"] != want[i] {
			t.Fatalf("line %d SeverityText=%v want %s", i, rec["SeverityText"], want[i])
		}
		if rec["severity"] != want[i] {
			t.Fatalf("line %d severity=%v", i, rec["severity"])
		}
		res, _ := rec["Resource"].(map[string]any)
		if res["service.name"] != "jobos-hub-test" {
			t.Fatalf("service.name=%v", res["service.name"])
		}
	}
}

func TestLWithoutInitDoesNotDeadlock(t *testing.T) {
	mu.Lock()
	active = nil
	mu.Unlock()

	done := make(chan struct{})
	go func() {
		_ = L()
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("L() deadlocked when called before Init")
	}
}

func TestGinRequestSeverities(t *testing.T) {
	gin.SetMode(gin.TestMode)
	var buf bytes.Buffer
	Init(Options{ServiceName: "hub", Exporter: "console", Writer: &buf, MinLevel: slog.LevelInfo})

	r := gin.New()
	r.Use(GinRecovery(), GinRequest())
	r.GET("/ok", func(c *gin.Context) { c.Status(200) })
	r.GET("/health", func(c *gin.Context) { c.Status(200) })
	r.GET("/nope", func(c *gin.Context) { c.Status(401) })
	r.GET("/boom", func(c *gin.Context) { c.Status(500) })

	for _, path := range []string{"/ok", "/health", "/nope", "/boom"} {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
	}

	out := buf.String()
	if strings.Contains(out, `"http.route":"/health"`) && strings.Contains(out, `"SeverityText":"INFO"`) {
		// health success should be quiet — fail if an INFO health line exists alone
		for _, line := range strings.Split(out, "\n") {
			if strings.Contains(line, `"/health"`) && strings.Contains(line, `"INFO"`) {
				t.Fatalf("successful /health should not INFO-log: %s", line)
			}
		}
	}
	if !strings.Contains(out, `"SeverityText":"WARN"`) || !strings.Contains(out, `"/nope"`) {
		t.Fatalf("expected WARN for 401: %s", out)
	}
	if !strings.Contains(out, `"SeverityText":"ERROR"`) || !strings.Contains(out, `"/boom"`) {
		t.Fatalf("expected ERROR for 500: %s", out)
	}
	_ = Shutdown(context.Background())
}
