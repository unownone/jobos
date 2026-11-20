package httpapi

import (
	"net/http"
	"net/http/cookiejar"
	"strings"
	"testing"
)

func TestA2AAnonymousAsksForAKeyAndSkillRoutesTheInbox(t *testing.T) {
	ts := testServer(t)
	defer ts.Close()
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}
	res := postJSON(t, client, ts.URL+"/api/auth/signup", `{"username":"ada","password":"long-enough"}`, "")
	csrf := res.Header.Get("X-CSRF")
	res.Body.Close()

	anon := postJSON(t, http.DefaultClient, ts.URL+"/a2a", `{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"parts":[{"kind":"text","text":"hello"}]}}}`, "")
	if !strings.Contains(readBody(anon), "Onboard the candidate profile") {
		t.Fatal("anonymous send before onboarding should ask for a profile")
	}

	res = putBody(t, client, ts.URL+"/api/candidate", "text/yaml", readyCandidateYAML, csrf)
	if res.StatusCode != 200 {
		t.Fatalf("candidate %d %s", res.StatusCode, readBody(res))
	}
	res.Body.Close()

	anon = postJSON(t, http.DefaultClient, ts.URL+"/a2a", `{"jsonrpc":"2.0","id":2,"method":"message/send","params":{"message":{"parts":[{"kind":"text","text":"hello"}]}}}`, "")
	body := readBody(anon)
	if !strings.Contains(body, `"state":"auth-required"`) || !strings.Contains(body, "Bearer") {
		t.Fatalf("anonymous send %s", body)
	}

	res = postJSON(t, client, ts.URL+"/a2a", `{"jsonrpc":"2.0","id":3,"method":"message/send","params":{"message":{"parts":[{"kind":"data","data":{"body":"skill routed note","skill_id":"hub.outreach"}}]}}}`, csrf)
	body = readBody(res)
	if !strings.Contains(body, `"state":"completed"`) || !strings.Contains(body, "skill routed note") && !strings.Contains(body, "hub_message_id") {
		t.Fatalf("skill send %s", body)
	}
	if !strings.Contains(body, "hub_message_id") {
		t.Fatalf("skill send missing hub message %s", body)
	}

	outreach := mintTrack(t, client, ts.URL, csrf, "outreach")
	req, _ := http.NewRequest(http.MethodGet, ts.URL+"/api/messages", nil)
	req.Header.Set("Authorization", "Bearer "+outreach)
	res, _ = http.DefaultClient.Do(req)
	if !strings.Contains(readBody(res), "skill routed note") {
		t.Fatal("outreach inbox missed the skill-routed note")
	}

	res = postJSON(t, client, ts.URL+"/a2a", `{"jsonrpc":"2.0","id":4,"method":"tasks/list","params":{}}`, csrf)
	listed := readBody(res)
	if !strings.Contains(listed, "auth-required") || !strings.Contains(listed, "completed") {
		t.Fatalf("tasks/list %s", listed)
	}
}
