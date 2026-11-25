package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/cookiejar"
	"strings"
	"testing"
)

func TestInviteMCPBootstrapAndAPIKeyAuth(t *testing.T) {
	ts := testServer(t)
	defer ts.Close()
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}

	res := postJSON(t, client, ts.URL+"/api/auth/signup", `{"username":"mcpops","password":"long-enough"}`, "")
	csrf := res.Header.Get("X-CSRF")
	res.Body.Close()
	res = putBody(t, client, ts.URL+"/api/candidate", "text/yaml", readyCandidateYAML, csrf)
	res.Body.Close()

	created := postJSON(t, client, ts.URL+"/api/invites", `{"track":"discovery","mode":"owner_then_agents","max_redemptions":3}`, csrf)
	body := readBody(created)
	if created.StatusCode != 200 {
		t.Fatalf("invite %d %s", created.StatusCode, body)
	}
	var payload struct {
		APIKey     string             `json:"api_key"`
		MCPURL     string             `json:"mcp_url"`
		JoinURL    string             `json:"join_url"`
		MCPClients []MCPClientSnippet `json:"mcp_clients"`
		Invite     struct {
			Redemptions int `json:"redemptions"`
		} `json:"invite"`
	}
	if err := json.Unmarshal([]byte(body), &payload); err != nil {
		t.Fatal(err)
	}
	if payload.APIKey == "" || !strings.HasPrefix(payload.APIKey, "jh_own_") {
		t.Fatalf("expected owner api key, got %q", payload.APIKey)
	}
	if payload.MCPURL == "" || !strings.HasSuffix(payload.MCPURL, "/mcp") {
		t.Fatalf("mcp_url %q", payload.MCPURL)
	}
	if payload.Invite.Redemptions != 1 {
		t.Fatalf("bootstrap should burn one redemption, got %d", payload.Invite.Redemptions)
	}
	if len(payload.MCPClients) < 4 {
		t.Fatalf("mcp_clients %#v", payload.MCPClients)
	}
	if !strings.Contains(payload.MCPClients[0].Config, payload.APIKey) {
		t.Fatalf("snippet missing key")
	}

	init := mcpCall(t, ts.URL, payload.APIKey, "", `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","clientInfo":{"name":"Cursor"}}}`)
	session := init.Header.Get("Mcp-Session-Id")
	initBody := readBody(init)
	if init.StatusCode != 200 || session == "" || !strings.Contains(initBody, "jobos") {
		t.Fatalf("api key init %d %s", init.StatusCode, initBody)
	}

	who := mcpCall(t, ts.URL, payload.APIKey, session, `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"whoami","arguments":{}}}`)
	whoBody := readBody(who)
	if who.StatusCode != 200 || !strings.Contains(whoBody, `\"role\": \"discovery\"`) {
		t.Fatalf("whoami %s", whoBody)
	}

	listed := mcpCall(t, ts.URL, payload.APIKey, session, `{"jsonrpc":"2.0","id":3,"method":"tools/list","params":{}}`)
	listBody := readBody(listed)
	if !strings.Contains(listBody, `"name":"queue_claim"`) || !strings.Contains(listBody, `"name":"list_skills"`) {
		t.Fatalf("tools/list missing parity tools: %s", listBody)
	}

	cand := mcpCall(t, ts.URL, payload.APIKey, session, `{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"candidate_status","arguments":{}}}`)
	candBody := readBody(cand)
	if !strings.Contains(candBody, `\"onboarded\": true`) && !strings.Contains(candBody, `"onboarded":true`) {
		t.Fatalf("candidate_status %s", candBody)
	}
}
