package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/cookiejar"
	"strings"
	"testing"
)

func TestOwnerOnlyNeedsAllowMultipleOwners(t *testing.T) {
	ts := testServer(t)
	defer ts.Close()
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}

	res := postJSON(t, client, ts.URL+"/api/auth/signup", `{"username":"ops","password":"long-enough"}`, "")
	csrf := res.Header.Get("X-CSRF")
	res.Body.Close()
	res = putBody(t, client, ts.URL+"/api/candidate", "text/yaml", readyCandidateYAML, csrf)
	res.Body.Close()

	first := postJSON(t, client, ts.URL+"/api/invites", `{"track":"outreach","mode":"owner_only","max_redemptions":1}`, csrf)
	body := readBody(first)
	if first.StatusCode != 200 {
		t.Fatalf("invite %d %s", first.StatusCode, body)
	}
	var created struct {
		Secret string `json:"secret"`
		Invite struct {
			ID string `json:"id"`
		} `json:"invite"`
	}
	if err := json.Unmarshal([]byte(body), &created); err != nil {
		t.Fatal(err)
	}
	join1 := postJSON(t, client, ts.URL+"/api/auth/join", `{"invite_id":"`+created.Invite.ID+`","s":"`+created.Secret+`","display_name":"outreach-owner-1"}`, "")
	j1 := readBody(join1)
	if join1.StatusCode != 200 || !strings.Contains(j1, `"kind":"owner"`) {
		t.Fatalf("first owner %d %s", join1.StatusCode, j1)
	}

	blocked := postJSON(t, client, ts.URL+"/api/invites", `{"track":"outreach","mode":"owner_only","max_redemptions":1}`, csrf)
	blockedBody := readBody(blocked)
	var blockedInv struct {
		Secret string `json:"secret"`
		Invite struct {
			ID string `json:"id"`
		} `json:"invite"`
	}
	_ = json.Unmarshal([]byte(blockedBody), &blockedInv)
	denied := postJSON(t, client, ts.URL+"/api/auth/join", `{"invite_id":"`+blockedInv.Invite.ID+`","s":"`+blockedInv.Secret+`","display_name":"outreach-owner-2"}`, "")
	if denied.StatusCode != 403 {
		t.Fatalf("expected 403 without flag, got %d %s", denied.StatusCode, readBody(denied))
	}

	flagged := postJSON(t, client, ts.URL+"/api/invites", `{"track":"outreach","mode":"owner_only","max_redemptions":1,"allow_multiple_owners":true}`, csrf)
	flagBody := readBody(flagged)
	var flaggedInv struct {
		Secret string `json:"secret"`
		Invite struct {
			ID                  string `json:"id"`
			AllowMultipleOwners bool   `json:"allow_multiple_owners"`
		} `json:"invite"`
	}
	if err := json.Unmarshal([]byte(flagBody), &flaggedInv); err != nil || !flaggedInv.Invite.AllowMultipleOwners {
		t.Fatalf("flagged invite %s", flagBody)
	}
	extra := postJSON(t, client, ts.URL+"/api/auth/join", `{"invite_id":"`+flaggedInv.Invite.ID+`","s":"`+flaggedInv.Secret+`","display_name":"outreach-owner-2"}`, "")
	extraBody := readBody(extra)
	if extra.StatusCode != 200 || !strings.Contains(extraBody, `"kind":"owner"`) {
		t.Fatalf("second owner %d %s", extra.StatusCode, extraBody)
	}
}

func TestOwnerThenAgentsSecondJoinIsAgent(t *testing.T) {
	ts := testServer(t)
	defer ts.Close()
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}

	res := postJSON(t, client, ts.URL+"/api/auth/signup", `{"username":"ops2","password":"long-enough"}`, "")
	csrf := res.Header.Get("X-CSRF")
	res.Body.Close()
	res = putBody(t, client, ts.URL+"/api/candidate", "text/yaml", readyCandidateYAML, csrf)
	res.Body.Close()

	created := postJSON(t, client, ts.URL+"/api/invites", `{"track":"discovery","mode":"owner_then_agents","max_redemptions":3,"allow_multiple_owners":true}`, csrf)
	body := readBody(created)
	var inv struct {
		Secret string `json:"secret"`
		Invite struct {
			ID string `json:"id"`
		} `json:"invite"`
	}
	if err := json.Unmarshal([]byte(body), &inv); err != nil {
		t.Fatal(err)
	}
	owner := postJSON(t, client, ts.URL+"/api/auth/join", `{"invite_id":"`+inv.Invite.ID+`","s":"`+inv.Secret+`","display_name":"disco-owner"}`, "")
	if owner.StatusCode != 200 || !strings.Contains(readBody(owner), `"kind":"owner"`) {
		t.Fatalf("owner join failed")
	}
	agent := postJSON(t, client, ts.URL+"/api/auth/join", `{"invite_id":"`+inv.Invite.ID+`","s":"`+inv.Secret+`","display_name":"disco-agent"}`, "")
	agentBody := readBody(agent)
	if agent.StatusCode != 200 || !strings.Contains(agentBody, `"kind":"agent"`) {
		t.Fatalf("second join should stay agent even with multi-owner flag: %d %s", agent.StatusCode, agentBody)
	}
}
