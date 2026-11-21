// Package telemetry configures Hub process logs for OTEL_LOGS_EXPORTER.
//
// Compose already sets OTEL_SERVICE_NAME and OTEL_LOGS_EXPORTER=console.
// This package emits OTEL-shaped JSON on stdout so Cloud Run / Coolify /
// collectors classify SeverityText correctly (ERROR / WARN / INFO).
package telemetry

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"os"
	"strings"
	"sync"
	"time"
)

// OTEL severity numbers (Logs Data Model).
const (
	SeverityTrace = 1
	SeverityDebug = 5
	SeverityInfo  = 9
	SeverityWarn  = 13
	SeverityError = 17
	SeverityFatal = 21
)

type Options struct {
	ServiceName string
	Exporter    string // console|stdout|none|off (otlp falls back to console)
	// MinLevel overrides env when non-nil. Nil means read OTEL_LOG_LEVEL / LOG_LEVEL.
	MinLevel *slog.Level
	Writer   io.Writer
}

// Level returns a pointer suitable for Options.MinLevel.
func Level(l slog.Level) *slog.Level { return &l }

var (
	mu      sync.Mutex
	active  *slog.Logger
	started Options
)

// Init installs the default slog logger from OTEL_* env (or opts overrides).
func Init(opts Options) *slog.Logger {
	mu.Lock()
	defer mu.Unlock()
	return initLocked(opts)
}

// L returns the process logger (Init first; otherwise a console default).
func L() *slog.Logger {
	mu.Lock()
	defer mu.Unlock()
	if active != nil {
		return active
	}
	return initLocked(Options{})
}

func initLocked(opts Options) *slog.Logger {
	if opts.ServiceName == "" {
		opts.ServiceName = firstNonEmpty(os.Getenv("OTEL_SERVICE_NAME"), "jobos-hub")
	}
	if opts.Exporter == "" {
		opts.Exporter = firstNonEmpty(os.Getenv("OTEL_LOGS_EXPORTER"), "console")
	}
	if opts.Writer == nil {
		opts.Writer = os.Stdout
	}
	minLevel := parseLevel(firstNonEmpty(os.Getenv("OTEL_LOG_LEVEL"), os.Getenv("LOG_LEVEL"), "info"))
	if opts.MinLevel != nil {
		minLevel = *opts.MinLevel
	}

	exporter := strings.ToLower(strings.TrimSpace(opts.Exporter))
	var handler slog.Handler
	switch exporter {
	case "none", "off", "false", "noop":
		handler = slog.NewJSONHandler(io.Discard, &slog.HandlerOptions{Level: minLevel})
	case "otlp", "otlphttp", "otlpgrpc":
		// Full OTLP SDK is not vendored here; console still carries SeverityText
		// so a sidecar/collector scraping stdout keeps working.
		_, _ = io.WriteString(os.Stderr, `{"SeverityText":"WARN","SeverityNumber":13,"Body":"OTEL_LOGS_EXPORTER=otlp requested; emitting console OTEL JSON instead","Resource":{"service.name":`+jsonString(opts.ServiceName)+`}}`+"\n")
		handler = newConsoleHandler(opts.Writer, opts.ServiceName, minLevel)
	default: // console, stdout, logging, …
		handler = newConsoleHandler(opts.Writer, opts.ServiceName, minLevel)
	}

	logger := slog.New(handler)
	slog.SetDefault(logger)
	active = logger
	started = opts
	return logger
}

// Shutdown is a no-op for the console exporter (kept for call-site symmetry).
func Shutdown(context.Context) error { return nil }

func ServiceName() string {
	mu.Lock()
	defer mu.Unlock()
	if started.ServiceName != "" {
		return started.ServiceName
	}
	return firstNonEmpty(os.Getenv("OTEL_SERVICE_NAME"), "jobos-hub")
}

type consoleHandler struct {
	w       io.Writer
	service string
	min     slog.Level
	mu      *sync.Mutex
	// attrs keys are already group-qualified when stored via WithAttrs.
	attrs  []slog.Attr
	groups []string
}

func newConsoleHandler(w io.Writer, service string, min slog.Level) *consoleHandler {
	return &consoleHandler{w: w, service: service, min: min, mu: &sync.Mutex{}}
}

func (h *consoleHandler) Enabled(_ context.Context, level slog.Level) bool {
	return level >= h.min
}

func (h *consoleHandler) Handle(_ context.Context, r slog.Record) error {
	sevText, sevNum := severityOf(r.Level)
	attrs := map[string]any{}
	for _, a := range h.attrs {
		attrs[a.Key] = attrValue(a.Value)
	}
	prefix := groupPrefix(h.groups)
	r.Attrs(func(a slog.Attr) bool {
		key := a.Key
		if prefix != "" {
			key = prefix + key
		}
		attrs[key] = attrValue(a.Value)
		return true
	})

	rec := map[string]any{
		"Timestamp":         r.Time.UTC().Format(time.RFC3339Nano),
		"ObservedTimestamp": time.Now().UTC().Format(time.RFC3339Nano),
		"SeverityText":      sevText,
		"SeverityNumber":    sevNum,
		// Cloud Logging / many scrapers also key off "severity".
		"severity": sevText,
		"Body":     r.Message,
		"message":  r.Message,
		"Resource": map[string]any{
			"service.name": h.service,
		},
	}
	if len(attrs) > 0 {
		rec["Attributes"] = attrs
	}

	h.mu.Lock()
	defer h.mu.Unlock()
	enc := json.NewEncoder(h.w)
	enc.SetEscapeHTML(false)
	return enc.Encode(rec)
}

func (h *consoleHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	next := *h
	prefix := groupPrefix(h.groups)
	qualified := make([]slog.Attr, 0, len(attrs))
	for _, a := range attrs {
		key := a.Key
		if prefix != "" {
			key = prefix + key
		}
		qualified = append(qualified, slog.Attr{Key: key, Value: a.Value})
	}
	next.attrs = append(append([]slog.Attr{}, h.attrs...), qualified...)
	return &next
}

func (h *consoleHandler) WithGroup(name string) slog.Handler {
	next := *h
	next.groups = append(append([]string{}, h.groups...), name)
	return &next
}

func groupPrefix(groups []string) string {
	if len(groups) == 0 {
		return ""
	}
	return strings.Join(groups, ".") + "."
}

func severityOf(level slog.Level) (string, int) {
	switch {
	case level >= slog.LevelError+4:
		return "FATAL", SeverityFatal
	case level >= slog.LevelError:
		return "ERROR", SeverityError
	case level >= slog.LevelWarn:
		return "WARN", SeverityWarn
	case level >= slog.LevelInfo:
		return "INFO", SeverityInfo
	case level >= slog.LevelDebug:
		return "DEBUG", SeverityDebug
	default:
		return "TRACE", SeverityTrace
	}
}

func attrValue(v slog.Value) any {
	v = v.Resolve()
	switch v.Kind() {
	case slog.KindString:
		return v.String()
	case slog.KindInt64:
		return v.Int64()
	case slog.KindUint64:
		return v.Uint64()
	case slog.KindFloat64:
		return v.Float64()
	case slog.KindBool:
		return v.Bool()
	case slog.KindDuration:
		return v.Duration().String()
	case slog.KindTime:
		return v.Time().UTC().Format(time.RFC3339Nano)
	case slog.KindGroup:
		out := map[string]any{}
		for _, a := range v.Group() {
			out[a.Key] = attrValue(a.Value)
		}
		return out
	default:
		return v.Any()
	}
}

func parseLevel(raw string) slog.Level {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "trace":
		return slog.LevelDebug - 4
	case "debug":
		return slog.LevelDebug
	case "warn", "warning":
		return slog.LevelWarn
	case "error":
		return slog.LevelError
	case "fatal":
		return slog.LevelError + 4
	default:
		return slog.LevelInfo
	}
}

func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		if strings.TrimSpace(v) != "" {
			return strings.TrimSpace(v)
		}
	}
	return ""
}

func jsonString(s string) string {
	b, _ := json.Marshal(s)
	return string(b)
}
