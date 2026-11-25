package httpapi

import (
	"crypto/tls"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/unownone/jobos/server/internal/config"
)

func TestPublicURLIgnoresUntrustedForwardedHost(t *testing.T) {
	gin.SetMode(gin.TestMode)
	srv := &Server{Cfg: config.Config{}} // empty PublicURL — prod must set HUB_PUBLIC_* 
	req := httptest.NewRequest(http.MethodGet, "http://127.0.0.1:8080/api/invites", nil)
	req.Header.Set("X-Forwarded-Host", "evil.attacker.example, run.app")
	req.Header.Set("X-Forwarded-Proto", "https, http")
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = req
	got := srv.publicURL(c)
	if strings.Contains(got, "evil.attacker.example") {
		t.Fatalf("attacker X-Forwarded-Host must not become invite origin: %q", got)
	}
	if got != "https://127.0.0.1:8080" {
		t.Fatalf("got %q want Request.Host with forwarded proto", got)
	}
}

func TestPublicURLConfiguredWins(t *testing.T) {
	gin.SetMode(gin.TestMode)
	srv := &Server{Cfg: config.Config{PublicURL: "https://ikr.one"}}
	req := httptest.NewRequest(http.MethodGet, "http://run.app/api/invites", nil)
	req.Header.Set("X-Forwarded-Host", "evil.attacker.example")
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = req
	if got := srv.publicURL(c); got != "https://ikr.one" {
		t.Fatalf("got %q", got)
	}
}

func TestPublicURLTLSWithoutForwarded(t *testing.T) {
	gin.SetMode(gin.TestMode)
	srv := &Server{Cfg: config.Config{}}
	req := httptest.NewRequest(http.MethodGet, "https://hub.example/api/invites", nil)
	req.TLS = &tls.ConnectionState{}
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = req
	if got := srv.publicURL(c); got != "https://hub.example" {
		t.Fatalf("got %q", got)
	}
}
