package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/cookiejar"
	"strings"
	"testing"
)

func TestDisabledAgentKeyDoesNotStayCached(t *testing.T) {
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
	res = putBody(t, client, ts.URL+"/api/candidate", "text/yaml", readyCandidateYAML, csrf)
	if res.StatusCode != 200 {
		t.Fatalf("candidate %d %s", res.StatusCode, readBody(res))
	}
	res.Body.Close()

	res = postJSON(t, client, ts.URL+"/api/agents", `{"display_name":"applier","track":"application"}`, csrf)
	body := readBody(res)
	if res.StatusCode != 200 {
		t.Fatalf("agent %d %s", res.StatusCode, body)
	}
	var created struct {
		APIKey string `json:"api_key"`
		User   struct {
			ID string `json:"id"`
		} `json:"user"`
	}
	if err := json.Unmarshal([]byte(body), &created); err != nil || created.APIKey == "" || created.User.ID == "" {
		t.Fatalf("agent payload %s", body)
	}

	me := func() int {
		t.Helper()
		req, err := http.NewRequest(http.MethodGet, ts.URL+"/api/auth/me", nil)
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("Authorization", "Bearer "+created.APIKey)
		res, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer res.Body.Close()
		_, _ = io.Copy(io.Discard, res.Body)
		return res.StatusCode
	}
	if me() != 200 || me() != 200 {
		t.Fatal("expected the cached key to authenticate")
	}

	res = postJSON(t, client, ts.URL+"/api/agents/"+created.User.ID+"/disable", `{}`, csrf)
	if res.StatusCode != 200 {
		t.Fatalf("disable %d %s", res.StatusCode, readBody(res))
	}
	res.Body.Close()
	if code := me(); code != 401 {
		t.Fatalf("disabled key status %d", code)
	}
}

func TestHeartbeatRecallRefreshesAfterMemoryWrite(t *testing.T) {
	ts := testServer(t)
	defer ts.Close()
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}
	res := postJSON(t, client, ts.URL+"/api/auth/signup", `{"username":"ada","password":"long-enough"}`, "")
	csrf := res.Header.Get("X-CSRF")
	res.Body.Close()
	res = putBody(t, client, ts.URL+"/api/candidate", "text/yaml", readyCandidateYAML, csrf)
	res.Body.Close()

	beat := func() string {
		t.Helper()
		res := postJSON(t, client, ts.URL+"/api/presence/heartbeat", `{}`, csrf)
		body := readBody(res)
		if res.StatusCode != 200 {
			t.Fatalf("heartbeat %d %s", res.StatusCode, body)
		}
		return body
	}
	first := beat()
	note := `{"pod":"common","kind":"hub_note","title":"Portal quirk","body":"The portal keeps the draft only when the tab stays open."}`
	res = postJSON(t, client, ts.URL+"/api/memory/items", note, csrf)
	if res.StatusCode != 201 && res.StatusCode != 200 {
		t.Fatalf("memory %d %s", res.StatusCode, readBody(res))
	}
	res.Body.Close()
	second := beat()
	if strings.Contains(first, "Portal quirk") || !strings.Contains(second, "Portal quirk") {
		t.Fatalf("recall cache did not refresh\nfirst %s\nsecond %s", first, second)
	}
}
