package httpapi

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/unownone/jobos/server/internal/blob"
	"github.com/unownone/jobos/server/internal/cache"
	"github.com/unownone/jobos/server/internal/config"
	"github.com/unownone/jobos/server/internal/realtime"
	"github.com/unownone/jobos/server/internal/store"
)

func TestSPAServesIndexAndLeavesAPI(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "index.html"), []byte("find-jobs"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(dir, "assets"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "assets", "app.js"), []byte("spa-js"), 0o644); err != nil {
		t.Fatal(err)
	}
	srv := New(config.Config{WebRoot: dir}, store.NewMemory(), blob.NewMemory(), cache.NewMemory(), realtime.New())
	ts := httptest.NewServer(srv.Router())
	defer ts.Close()

	page := getBody(t, ts.URL+"/login")
	if !strings.Contains(page, "find-jobs") {
		t.Fatalf("login page %s", page)
	}
	asset := getBody(t, ts.URL+"/assets/app.js")
	if asset != "spa-js" {
		t.Fatalf("asset %s", asset)
	}
	health := getBody(t, ts.URL+"/health")
	if !strings.Contains(health, `"ok":true`) {
		t.Fatalf("health %s", health)
	}
	res, err := http.Get(ts.URL + "/api/jobs")
	if err != nil {
		t.Fatal(err)
	}
	body := readBody(res)
	if res.StatusCode != 401 || strings.Contains(body, "find-jobs") {
		t.Fatalf("api %d %s", res.StatusCode, body)
	}
	file, ok := spaFile(dir, "/../../etc/passwd")
	if !ok || !strings.HasPrefix(file, dir) {
		t.Fatalf("escape %q %v", file, ok)
	}
}

func getBody(t *testing.T, url string) string {
	t.Helper()
	res, err := http.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	return readBody(res)
}
