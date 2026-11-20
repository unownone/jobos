package httpapi

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"github.com/unownone/jobos/server/internal/blob"
	"github.com/unownone/jobos/server/internal/cache"
	"github.com/unownone/jobos/server/internal/config"
	"github.com/unownone/jobos/server/internal/realtime"
	"github.com/unownone/jobos/server/internal/store"
)

func testServer(t *testing.T) *httptest.Server {
	t.Helper()
	srv := New(config.Config{}, store.NewMemory(), blob.NewMemory(), cache.NewMemory(), realtime.New())
	if n := srv.Seed(context.Background()); n < 5 {
		t.Fatalf("seeded %d", n)
	}
	return httptest.NewServer(srv.Router())
}

func TestSignupOnboardJobQueueAndStream(t *testing.T) {
	ts := testServer(t)
	defer ts.Close()
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}

	res := postJSON(t, client, ts.URL+"/api/auth/signup", `{"username":"ada","password":"long-enough"}`, "")
	if res.StatusCode != 200 {
		t.Fatalf("signup %d %s", res.StatusCode, readBody(res))
	}
	csrf := res.Header.Get("X-CSRF")
	res.Body.Close()

	res = putBody(t, client, ts.URL+"/api/candidate", "text/yaml", "name: Ada Lovelace\ntitles:\n  - Engineer\n", csrf)
	if res.StatusCode != 200 {
		t.Fatalf("candidate %d %s", res.StatusCode, readBody(res))
	}
	res = putBody(t, client, ts.URL+"/api/candidate/resume", "application/pdf", "%PDF-1.4 resume", csrf)
	if res.StatusCode != 200 || !strings.Contains(readBody(res), `"driver":"memory"`) {
		t.Fatalf("resume %s", readBody(res))
	}

	res = postJSON(t, client, ts.URL+"/api/jobs", `{"company":"Analytical Engines","title":"Engineer","status":"discovered","apply_url":"https://example.com/jobs/1"}`, csrf)
	if res.StatusCode != 201 {
		t.Fatalf("create %d %s", res.StatusCode, readBody(res))
	}
	res = patchJSON(t, client, ts.URL+"/api/jobs/"+jobID(t, client, ts.URL), `{"status":"apply_ready","apply_packet":{"url":"https://example.com/jobs/1","steps":["submit"]}}`, csrf)
	if res.StatusCode != 200 {
		t.Fatalf("patch %d %s", res.StatusCode, readBody(res))
	}

	invite := mintAgent(t, client, ts.URL, csrf)
	agent := &http.Client{}
	req, _ := http.NewRequest(http.MethodPost, ts.URL+"/api/queue/claim", strings.NewReader(`{"kinds":["apply.ready"]}`))
	req.Header.Set("Authorization", "Bearer "+invite)
	req.Header.Set("Content-Type", "application/json")
	res, err := agent.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	body := readBody(res)
	if res.StatusCode != 200 || !strings.Contains(body, "apply.ready") {
		t.Fatalf("claim %d %s", res.StatusCode, body)
	}

	health, err := client.Get(ts.URL + "/health")
	if err != nil {
		t.Fatal(err)
	}
	hb := readBody(health)
	if !strings.Contains(hb, `"rabbitmq":false`) || !strings.Contains(hb, `"store":"memory"`) {
		t.Fatalf("health %s", hb)
	}

	req, _ = http.NewRequest(http.MethodGet, ts.URL+"/api/stream", nil)
	req.Header.Set("Authorization", "Bearer "+invite)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	req = req.WithContext(ctx)
	stream, err := agent.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer stream.Body.Close()
	if stream.StatusCode != 200 || !strings.Contains(stream.Header.Get("Content-Type"), "text/event-stream") {
		t.Fatalf("stream %d %s", stream.StatusCode, stream.Header.Get("Content-Type"))
	}

	wsURL := "ws" + strings.TrimPrefix(ts.URL, "http") + "/ws?access_token=" + invite
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	var hello map[string]any
	if err := conn.ReadJSON(&hello); err != nil || hello["event"] != "hello" {
		t.Fatalf("ws hello %#v %v", hello, err)
	}
	if err := conn.WriteJSON(map[string]string{"type": "heartbeat", "status": "active"}); err != nil {
		t.Fatal(err)
	}
}

func mintAgent(t *testing.T, client *http.Client, base, csrf string) string {
	t.Helper()
	res := postJSON(t, client, base+"/api/agents", `{"display_name":"applier","track":"application"}`, csrf)
	body := readBody(res)
	if res.StatusCode != 200 {
		t.Fatalf("agent %d %s", res.StatusCode, body)
	}
	var payload struct {
		APIKey string `json:"api_key"`
	}
	if err := json.Unmarshal([]byte(body), &payload); err != nil || payload.APIKey == "" {
		t.Fatalf("key %s", body)
	}
	return payload.APIKey
}

func jobID(t *testing.T, client *http.Client, base string) string {
	t.Helper()
	res, err := client.Get(base + "/api/jobs")
	if err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Jobs []struct {
			ID string `json:"id"`
		} `json:"jobs"`
	}
	if err := json.NewDecoder(res.Body).Decode(&payload); err != nil {
		t.Fatal(err)
	}
	res.Body.Close()
	if len(payload.Jobs) != 1 {
		t.Fatalf("jobs %#v", payload.Jobs)
	}
	return payload.Jobs[0].ID
}

func postJSON(t *testing.T, client *http.Client, url, body, csrf string) *http.Response {
	t.Helper()
	return send(t, client, http.MethodPost, url, "application/json", body, csrf)
}

func patchJSON(t *testing.T, client *http.Client, url, body, csrf string) *http.Response {
	t.Helper()
	return send(t, client, http.MethodPatch, url, "application/json", body, csrf)
}

func putBody(t *testing.T, client *http.Client, url, ctype, body, csrf string) *http.Response {
	t.Helper()
	return send(t, client, http.MethodPut, url, ctype, body, csrf)
}

func send(t *testing.T, client *http.Client, method, url, ctype, body, csrf string) *http.Response {
	t.Helper()
	req, _ := http.NewRequest(method, url, strings.NewReader(body))
	req.Header.Set("Content-Type", ctype)
	if csrf != "" {
		req.Header.Set("X-CSRF", csrf)
	}
	res, err := client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	return res
}

func TestPackMCPAndMemoryCaps(t *testing.T) {
	srv := New(config.Config{}, store.NewMemory(), blob.NewMemory(), cache.NewMemory(), realtime.New())
	root, err := filepath.Abs(filepath.Join("..", "..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	srv.Cfg.RepoRoot = root
	if n := srv.Seed(context.Background()); n < 5 {
		t.Fatalf("seeded %d", n)
	}
	ts := httptest.NewServer(srv.Router())
	defer ts.Close()
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}
	res := postJSON(t, client, ts.URL+"/api/auth/signup", `{"username":"ada","password":"long-enough"}`, "")
	csrf := res.Header.Get("X-CSRF")
	res.Body.Close()
	res = putBody(t, client, ts.URL+"/api/candidate", "text/yaml", "name: Ada Lovelace\ntitles:\n  - Engineer\n", csrf)
	if res.StatusCode != 200 {
		t.Fatalf("candidate %s", readBody(res))
	}
	res.Body.Close()

	res = send(t, client, http.MethodGet, ts.URL+"/api/packs/current/skills.zip", "", "", csrf)
	raw, _ := io.ReadAll(res.Body)
	res.Body.Close()
	if res.StatusCode != 200 {
		t.Fatalf("zip %d %s", res.StatusCode, raw)
	}
	zr, err := zip.NewReader(bytes.NewReader(raw), int64(len(raw)))
	if err != nil || len(zr.File) == 0 {
		t.Fatalf("zip open %v files=%d", err, len(zr.File))
	}

	res = send(t, client, http.MethodGet, ts.URL+"/api/mcp/hosted/indeed.json", "", "", csrf)
	hosted := readBody(res)
	if res.StatusCode != 200 || !strings.Contains(hosted, "indeed") {
		t.Fatalf("hosted mcp %d %s", res.StatusCode, hosted)
	}

	res, err = client.Get(ts.URL + "/api/registry/mcps")
	if err != nil {
		t.Fatal(err)
	}
	var listed struct {
		Count int `json:"count"`
	}
	if err := json.NewDecoder(res.Body).Decode(&listed); err != nil || listed.Count < 1 {
		t.Fatalf("mcps %d %v", res.StatusCode, err)
	}
	res.Body.Close()

	note := `{"pod":"worker","kind":"working_note","body":"Greenhouse times out after the second page."}`
	for i := 0; i < 6; i++ {
		res = postJSON(t, client, ts.URL+"/api/memory/items", note, csrf)
		if res.StatusCode != 201 {
			t.Fatalf("memory %d %s", res.StatusCode, readBody(res))
		}
		res.Body.Close()
	}
	res = postJSON(t, client, ts.URL+"/api/memory/items", note, csrf)
	if res.StatusCode != 429 {
		t.Fatalf("cap status %d %s", res.StatusCode, readBody(res))
	}
	res.Body.Close()
}

func readBody(res *http.Response) string {
	defer res.Body.Close()
	b, _ := io.ReadAll(res.Body)
	return string(b)
}
