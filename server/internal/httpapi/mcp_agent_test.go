package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"strings"
	"testing"

	"github.com/unownone/jobos/server/internal/agentflow"
)

func TestAgentMCPConnect(t *testing.T) {
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
		t.Fatalf("candidate %s", readBody(res))
	}
	res.Body.Close()

	res = postJSON(t, client, ts.URL+"/oauth/register", `{"client_name":"Cursor","redirect_uris":["http://127.0.0.1:9/cb"],"token_endpoint_auth_method":"none"}`, "")
	body := readBody(res)
	if res.StatusCode != 201 || !strings.Contains(body, "jhmcp_cid_") {
		t.Fatalf("register %d %s", res.StatusCode, body)
	}
	var registered map[string]any
	if err := json.Unmarshal([]byte(body), &registered); err != nil {
		t.Fatal(err)
	}
	clientID := registered["client_id"].(string)
	verifier := strings.Repeat("a", 64)
	challenge := agentflow.PKCSES256(verifier)
	approve := `{"client_id":"` + clientID + `","redirect_uri":"http://127.0.0.1:9/cb","code_challenge":"` + challenge + `","code_challenge_method":"S256","state":"st","decision":"approve"}`
	res = postJSON(t, client, ts.URL+"/oauth/authorize", approve, csrf)
	body = readBody(res)
	if res.StatusCode != 200 || !strings.Contains(body, "jhmcp_cd_") {
		t.Fatalf("authorize %d %s", res.StatusCode, body)
	}
	var approved map[string]string
	_ = json.Unmarshal([]byte(body), &approved)
	parsed, _ := url.Parse(approved["redirect"])
	code := parsed.Query().Get("code")

	form := url.Values{"grant_type": {"authorization_code"}, "client_id": {clientID}, "code": {code}, "redirect_uri": {"http://127.0.0.1:9/cb"}, "code_verifier": {verifier}}
	res, err := client.PostForm(ts.URL+"/oauth/token", form)
	if err != nil {
		t.Fatal(err)
	}
	body = readBody(res)
	if res.StatusCode != 200 || !strings.Contains(body, "jhmcp_at_") {
		t.Fatalf("token %d %s", res.StatusCode, body)
	}
	var tok map[string]any
	_ = json.Unmarshal([]byte(body), &tok)
	access := tok["access_token"].(string)

	meta, err := client.Get(ts.URL + "/.well-known/oauth-protected-resource/mcp")
	if err != nil || meta.StatusCode != 200 || !strings.Contains(readBody(meta), "/mcp") {
		t.Fatal("metadata")
	}
	denied, _ := client.Get(ts.URL + "/mcp")
	if denied.StatusCode != 405 {
		t.Fatalf("get mcp %d", denied.StatusCode)
	}
	denied.Body.Close()

	init := mcpCall(t, ts.URL, access, "", `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","clientInfo":{"name":"Cursor"}}}`)
	session := init.Header.Get("Mcp-Session-Id")
	initBody := readBody(init)
	if init.StatusCode != 200 || session == "" || !strings.Contains(initBody, "jobos") {
		t.Fatalf("init %d %s", init.StatusCode, initBody)
	}
	lanes := mcpCall(t, ts.URL, access, session, `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"set_session_lanes","arguments":{"lanes":["find","apply"]}}}`)
	lanesBody := readBody(lanes)
	if lanes.StatusCode != 200 || !strings.Contains(lanesBody, "find") {
		t.Fatalf("lanes %d %s", lanes.StatusCode, lanesBody)
	}
	caps := mcpCall(t, ts.URL, access, session, `{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"report_capabilities","arguments":{"browser":true,"email":false}}}`)
	capsBody := readBody(caps)
	if !strings.Contains(capsBody, "reported") {
		t.Fatal(capsBody)
	}
	eval := mcpCall(t, ts.URL, access, session, `{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"evaluate_lane","arguments":{"lane":"find"}}}`)
	evalBody := readBody(eval)
	if !strings.Contains(evalBody, "job-discovery") || strings.Contains(evalBody, `"isError":true`) {
		t.Fatal(evalBody)
	}
	start := mcpCall(t, ts.URL, access, session, `{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"start_loop","arguments":{"lane":"find"}}}`)
	startBody := readBody(start)
	if !strings.Contains(startBody, "create_job") {
		t.Fatalf("loop %s", startBody)
	}
	status, _ := http.NewRequest(http.MethodGet, ts.URL+"/api/agent/status", nil)
	status.Header.Set("X-CSRF", csrf)
	res, err = client.Do(status)
	if err != nil {
		t.Fatal(err)
	}
	statusBody := readBody(res)
	if !strings.Contains(statusBody, "connected") {
		t.Fatal(statusBody)
	}
}

func mcpCall(t *testing.T, base, token, session, payload string) *http.Response {
	t.Helper()
	req, err := http.NewRequest(http.MethodPost, base+"/mcp", strings.NewReader(payload))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	if session != "" {
		req.Header.Set("Mcp-Session-Id", session)
	}
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	return res
}
