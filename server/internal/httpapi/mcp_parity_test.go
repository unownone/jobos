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

func TestMCPParityInvitesAndJobsViaAdminOAuth(t *testing.T) {
	ts := testServer(t)
	defer ts.Close()
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}

	res := postJSON(t, client, ts.URL+"/api/auth/signup", `{"username":"parityops","password":"long-enough"}`, "")
	csrf := res.Header.Get("X-CSRF")
	res.Body.Close()
	res = putBody(t, client, ts.URL+"/api/candidate", "text/yaml", readyCandidateYAML, csrf)
	res.Body.Close()

	access := oauthAccessToken(t, client, ts.URL, csrf)

	init := mcpCall(t, ts.URL, access, "", `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","clientInfo":{"name":"Parity"}}}`)
	session := init.Header.Get("Mcp-Session-Id")
	if init.StatusCode != 200 || session == "" {
		t.Fatalf("init %d %s", init.StatusCode, readBody(init))
	}

	listed := mcpCall(t, ts.URL, access, session, `{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}`)
	listBody := readBody(listed)
	for _, name := range []string{"create_invite", "list_invites", "meta", "create_job", "memory_pods", "create_message", "export_ledger"} {
		if !strings.Contains(listBody, `"name":"`+name+`"`) {
			t.Fatalf("tools/list missing %s", name)
		}
	}

	meta := mcpCall(t, ts.URL, access, session, `{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"meta","arguments":{}}}`)
	metaBody := readBody(meta)
	if !strings.Contains(metaBody, "prefer long-lived Hub API key") {
		t.Fatalf("meta %s", metaBody)
	}

	inv := mcpCall(t, ts.URL, access, session, `{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"create_invite","arguments":{"track":"application","mode":"agents_only","max_redemptions":2}}}`)
	invBody := readBody(inv)
	if strings.Contains(invBody, `"isError": true`) || strings.Contains(invBody, `"isError":true`) {
		t.Fatalf("create_invite %s", invBody)
	}
	if !strings.Contains(invBody, "jh_agt_") {
		t.Fatalf("create_invite missing api key %s", invBody)
	}
	if !strings.Contains(invBody, "mcp_clients") || !strings.Contains(invBody, "Cursor") {
		t.Fatalf("create_invite missing snippets %s", invBody)
	}

	pods := mcpCall(t, ts.URL, access, session, `{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"memory_pods","arguments":{}}}`)
	podsBody := readBody(pods)
	if !strings.Contains(podsBody, "common") {
		t.Fatalf("memory_pods %s", podsBody)
	}

	export := mcpCall(t, ts.URL, access, session, `{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"export_ledger","arguments":{}}}`)
	exportBody := readBody(export)
	if !strings.Contains(exportBody, "exported_at") {
		t.Fatalf("export_ledger %s", exportBody)
	}
}

func TestMCPAPIKeyJobAndQueueParity(t *testing.T) {
	ts := testServer(t)
	defer ts.Close()
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}

	res := postJSON(t, client, ts.URL+"/api/auth/signup", `{"username":"finder","password":"long-enough"}`, "")
	csrf := res.Header.Get("X-CSRF")
	res.Body.Close()
	res = putBody(t, client, ts.URL+"/api/candidate", "text/yaml", readyCandidateYAML, csrf)
	res.Body.Close()

	created := postJSON(t, client, ts.URL+"/api/invites", `{"track":"discovery","mode":"owner_then_agents","max_redemptions":3}`, csrf)
	body := readBody(created)
	var payload struct {
		APIKey string `json:"api_key"`
	}
	if err := json.Unmarshal([]byte(body), &payload); err != nil || payload.APIKey == "" {
		t.Fatalf("invite %s", body)
	}

	init := mcpCall(t, ts.URL, payload.APIKey, "", `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","clientInfo":{"name":"Cursor"}}}`)
	session := init.Header.Get("Mcp-Session-Id")
	readBody(init)

	lanes := mcpCall(t, ts.URL, payload.APIKey, session, `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"set_session_lanes","arguments":{"lanes":["find"]}}}`)
	readBody(lanes)
	caps := mcpCall(t, ts.URL, payload.APIKey, session, `{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"report_capabilities","arguments":{"browser":true,"email":false}}}`)
	readBody(caps)

	job := mcpCall(t, ts.URL, payload.APIKey, session, `{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"create_job","arguments":{"company":"Acme","title":"SWE","url":"https://example.com/j"}}}`)
	jobBody := readBody(job)
	if strings.Contains(jobBody, `"isError":true`) || strings.Contains(jobBody, `"isError": true`) {
		t.Fatalf("create_job %s", jobBody)
	}
	if !strings.Contains(jobBody, "Acme") {
		t.Fatalf("create_job missing company %s", jobBody)
	}

	listed := mcpCall(t, ts.URL, payload.APIKey, session, `{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"list_jobs","arguments":{}}}`)
	listBody := readBody(listed)
	if !strings.Contains(listBody, "Acme") {
		t.Fatalf("list_jobs %s", listBody)
	}

	mem := mcpCall(t, ts.URL, payload.APIKey, session, `{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"write_memory","arguments":{"kind":"note","body":"portal quirk","pod":"common","title":"tip"}}}`)
	memBody := readBody(mem)
	if strings.Contains(memBody, `"isError":true`) || strings.Contains(memBody, `"isError": true`) {
		t.Fatalf("write_memory %s", memBody)
	}
}

func oauthAccessToken(t *testing.T, client *http.Client, base, csrf string) string {
	t.Helper()
	res := postJSON(t, client, base+"/oauth/register", `{"client_name":"Parity","redirect_uris":["http://127.0.0.1:9/cb"],"token_endpoint_auth_method":"none"}`, "")
	body := readBody(res)
	var registered map[string]any
	if err := json.Unmarshal([]byte(body), &registered); err != nil {
		t.Fatal(err)
	}
	clientID := registered["client_id"].(string)
	verifier := strings.Repeat("b", 64)
	challenge := agentflow.PKCSES256(verifier)
	approve := `{"client_id":"` + clientID + `","redirect_uri":"http://127.0.0.1:9/cb","code_challenge":"` + challenge + `","code_challenge_method":"S256","state":"st","decision":"approve"}`
	res = postJSON(t, client, base+"/oauth/authorize", approve, csrf)
	body = readBody(res)
	var approved map[string]string
	_ = json.Unmarshal([]byte(body), &approved)
	parsed, _ := url.Parse(approved["redirect"])
	code := parsed.Query().Get("code")
	form := url.Values{"grant_type": {"authorization_code"}, "client_id": {clientID}, "code": {code}, "redirect_uri": {"http://127.0.0.1:9/cb"}, "code_verifier": {verifier}}
	res, err := client.PostForm(base+"/oauth/token", form)
	if err != nil {
		t.Fatal(err)
	}
	body = readBody(res)
	var tok map[string]any
	_ = json.Unmarshal([]byte(body), &tok)
	access, _ := tok["access_token"].(string)
	if access == "" {
		t.Fatalf("token %s", body)
	}
	return access
}
