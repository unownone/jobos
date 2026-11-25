package httpapi

import (
	"crypto/tls"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/unownone/jobos/server/internal/config"
)

func TestPublicURLUsesForwardedHostAndProto(t *testing.T) {
	gin.SetMode(gin.TestMode)
	srv := &Server{Cfg: config.Config{}}
	req := httptest.NewRequest(http.MethodGet, "http://127.0.0.1:8080/api/invites", nil)
	req.Header.Set("X-Forwarded-Host", "ikr.one, run.app")
	req.Header.Set("X-Forwarded-Proto", "https, http")
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = req
	if got := srv.publicURL(c); got != "https://ikr.one" {
		t.Fatalf("got %q", got)
	}
}

func TestPublicURLConfiguredWins(t *testing.T) {
	gin.SetMode(gin.TestMode)
	srv := &Server{Cfg: config.Config{PublicURL: "https://ikr.one"}}
	req := httptest.NewRequest(http.MethodGet, "http://run.app/api/invites", nil)
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
