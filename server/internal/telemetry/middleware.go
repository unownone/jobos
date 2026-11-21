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
		c.Next()
		status := c.Writer.Status()
		latency := time.Since(start)
		route := routeOf(c)
		attrs := []any{
			"http.method", c.Request.Method,
			"http.route", route,
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
		quiet := route == "/health" || route == "/ready"
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
					"http.route", routeOf(c),
				)
				c.AbortWithStatus(http.StatusInternalServerError)
			}
		}()
		c.Next()
	}
}

// NoteFail attaches an API failure message to the Gin context so GinRequest
// can include it on the single request log line (avoids double-counting).
func NoteFail(c *gin.Context, msg string) {
	if c == nil || msg == "" {
		return
	}
	_ = c.Error(fmt.Errorf("%s", msg))
}

// FromRequest returns a logger with request route attrs when available.
func FromRequest(c *gin.Context) *slog.Logger {
	if c == nil || c.Request == nil {
		return L()
	}
	return L().With(
		"http.method", c.Request.Method,
		"http.route", routeOf(c),
	)
}

// routeOf prefers the matched Gin route template (low cardinality) and falls
// back to the raw path when nothing matched (e.g. 404).
func routeOf(c *gin.Context) string {
	if c == nil || c.Request == nil {
		return ""
	}
	if route := c.FullPath(); route != "" {
		return route
	}
	return c.Request.URL.Path
}
