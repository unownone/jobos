package httpapi

import (
	"os"
	"testing"

	"github.com/unownone/jobos/server/internal/telemetry"
)

func TestMain(m *testing.M) {
	telemetry.Init(telemetry.Options{Exporter: "none", ServiceName: "jobos-hub-test"})
	os.Exit(m.Run())
}
