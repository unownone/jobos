package telemetry

import (
	"fmt"
	"log/slog"
	"net/http"
	"runtime/debug"
	"time"

	"github.com/gin-gonic/gin"
)

// GinRequest logs each request with OTEL severity:
// 5xx → ERROR, 4xx → WARN, else INFO. Skips noisy probes unless they fail.
func GinRequest() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		path := c.Request.URL.Path
		c.Next()
		status := c.Writer.Status()
		latency := time.Since(start)
		attrs := []any{
			"http.method", c.Request.Method,
			"http.route", path,
			"http.status_code", status,
			"http.duration_ms", latency.Milliseconds(),
			"client.address", c.ClientIP(),
		}
		if reqID := c.GetHeader("X-Request-Id"); reqID != "" {
			attrs = append(attrs, "http.request_id", reqID)
		}
		if len(c.Errors) > 0 {
			attrs = append(attrs, "error.message", c.Errors.String())
		}

		log := L()
		quiet := path == "/health" || path == "/ready"
		switch {
		case status >= 500:
			log.Error("http request failed", attrs...)
		case status >= 400:
			log.Warn("http request rejected", attrs...)
		case quiet:
			// Successful probes stay quiet.
		default:
			log.Info("http request", attrs...)
		}
	}
}

// GinRecovery logs panics as FATAL/ERROR and returns 500.
func GinRecovery() gin.HandlerFunc {
	return func(c *gin.Context) {
		defer func() {
			if rec := recover(); rec != nil {
				L().Error("http panic",
					"error.message", fmt.Sprint(rec),
					"exception.stacktrace", string(debug.Stack()),
					"http.method", c.Request.Method,
					"http.route", c.Request.URL.Path,
				)
				c.AbortWithStatus(http.StatusInternalServerError)
			}
		}()
		c.Next()
	}
}

// HTTPFail logs API fail() responses: 5xx error, 4xx warn.
func HTTPFail(status int, msg string, attrs ...any) {
	fields := append([]any{"http.status_code", status, "error.message", msg}, attrs...)
	if status >= 500 {
		L().Error("api error", fields...)
		return
	}
	if status >= 400 {
		L().Warn("api rejected", fields...)
	}
}

// FromRequest returns a logger with request route attrs when available.
func FromRequest(c *gin.Context) *slog.Logger {
	if c == nil || c.Request == nil {
		return L()
	}
	return L().With(
		"http.method", c.Request.Method,
		"http.route", c.Request.URL.Path,
	)
}
