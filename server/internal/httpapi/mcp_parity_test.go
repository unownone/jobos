package httpapi

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/unownone/jobos/server/internal/agentflow"
	"github.com/unownone/jobos/server/internal/blob"
	"github.com/unownone/jobos/server/internal/cache"
	"github.com/unownone/jobos/server/internal/config"
	"github.com/unownone/jobos/server/internal/realtime"
	"github.com/unownone/jobos/server/internal/store"
	"github.com/unownone/jobos/server/internal/telemetry"
)

func TestMCPParitySurfacesViaTools(t *testing.T) {
	ts, repoRoot := parityTestServer(t)
	defer ts.Close()
	_ = repoRoot

	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}
	res := postJSON(t, client, ts.URL+"/api/auth/signup", `{"username":"parityadmin","password":"long-enough"}`, "")
	csrf := res.Header.Get("X-CSRF")
	res.Body.Close()
	res = putBody(t, client, ts.URL+"/api/candidate", "text/yaml", readyCandidateYAML, csrf)
	res.Body.Close()
	res = putBody(t, client, ts.URL+"/api/candidate/resume", "application/pdf", "%PDF-1.4 resume", csrf)
	res.Body.Close()

	// Admin OAuth MCP session
	access, session := mcpOAuthSession(t, client, ts.URL, csrf)

	listed := mcpCall(t, ts.URL, access, session, `{"jsonrpc":"2.0","id":10,"method":"tools/list","params":{}}`)
	listBody := readBody(listed)
	for _, name := range []string{
		"create_invite", "create_agent", "rotate_agent_key", "create_message",
		"create_skill", "fork_skill", "promote_recording", "skills_zip",
		"hygiene", "import_jobs", "export_ledger", "add_token_burn",
		"a2a_directory", "create_peer", "poll_events",
		"dashboard", "list_users", "seed_registry",
	} {
		if !strings.Contains(listBody, `"name":"`+name+`"`) {
			t.Fatalf("tools/list missing %s: %s", name, listBody)
		}
	}

	meta := mcpToolText(t, ts.URL, access, session, 11, "meta", `{}`)
	if !strings.Contains(meta, `"mcp": true`) && !strings.Contains(meta, `"mcp":true`) {
		t.Fatalf("meta %s", meta)
	}

	dash := mcpToolText(t, ts.URL, access, session, 110, "dashboard", `{}`)
	if !strings.Contains(dash, "counts") || !strings.Contains(dash, "candidate_onboarded") {
		t.Fatalf("dashboard %s", dash)
	}
	users := mcpToolText(t, ts.URL, access, session, 111, "list_users", `{"kind":"admin"}`)
	if !strings.Contains(users, `"count"`) || !(strings.Contains(users, `"kind": "admin"`) || strings.Contains(users, `"kind":"admin"`)) {
		t.Fatalf("list_users %s", users)
	}
	seed := mcpToolText(t, ts.URL, access, session, 112, "seed_registry", `{}`)
	if !strings.Contains(seed, `"seeded"`) {
		t.Fatalf("seed_registry %s", seed)
	}

	inviteText := mcpToolText(t, ts.URL, access, session, 12, "create_invite", `{"track":"discovery","mcp_bootstrap":true}`)
	if !strings.Contains(inviteText, "jh_own_") && !strings.Contains(inviteText, "jh_agt_") {
		t.Fatalf("create_invite missing api key: %s", inviteText)
	}
	var invitePayload struct {
		APIKey string `json:"api_key"`
		Invite struct {
			ID string `json:"id"`
		} `json:"invite"`
		User struct {
			ID string `json:"id"`
		} `json:"user"`
	}
	if err := json.Unmarshal([]byte(inviteText), &invitePayload); err != nil {
		t.Fatalf("invite decode %v %s", err, inviteText)
	}

	agentText := mcpToolText(t, ts.URL, access, session, 13, "create_agent", `{"display_name":"parity-bot","track":"discovery"}`)
	var agentPayload struct {
		APIKey string `json:"api_key"`
		User   struct {
			ID string `json:"id"`
		} `json:"user"`
	}
	if err := json.Unmarshal([]byte(agentText), &agentPayload); err != nil || agentPayload.APIKey == "" || agentPayload.User.ID == "" {
		t.Fatalf("create_agent %s", agentText)
	}
	rotated := mcpToolText(t, ts.URL, access, session, 14, "rotate_agent_key", `{"id":"`+agentPayload.User.ID+`"}`)
	if !strings.Contains(rotated, "jh_agt_") {
		t.Fatalf("rotate_agent_key %s", rotated)
	}

	msgText := mcpToolText(t, ts.URL, access, session, 15, "create_message", `{"body":"hello parity","to_track":"discovery"}`)
	var msgPayload struct {
		Message struct {
			ID string `json:"id"`
		} `json:"message"`
	}
	_ = json.Unmarshal([]byte(msgText), &msgPayload)
	if msgPayload.Message.ID == "" {
		t.Fatalf("create_message %s", msgText)
	}
	listedMsgs := mcpToolText(t, ts.URL, access, session, 16, "list_messages", `{}`)
	if !strings.Contains(listedMsgs, msgPayload.Message.ID) {
		t.Fatalf("list_messages %s", listedMsgs)
	}
	readMsg := mcpToolText(t, ts.URL, access, session, 17, "read_message", `{"id":"`+msgPayload.Message.ID+`"}`)
	if !strings.Contains(readMsg, `"read_at"`) {
		t.Fatalf("read_message %s", readMsg)
	}

	poll1 := mcpToolText(t, ts.URL, access, session, 18, "poll_events", `{"after_seq":0}`)
	if !strings.Contains(poll1, `"event": "message"`) && !strings.Contains(poll1, `"event":"message"`) {
		t.Fatalf("poll_events missing message publish: %s", poll1)
	}
	var pollPayload struct {
		NextSeq int64  `json:"next_seq"`
		Count   int    `json:"count"`
		Epoch   string `json:"epoch"`
	}
	_ = json.Unmarshal([]byte(poll1), &pollPayload)
	if pollPayload.Count < 1 || pollPayload.NextSeq < 1 || pollPayload.Epoch == "" {
		t.Fatalf("poll_events seq %#v %s", pollPayload, poll1)
	}
	poll2 := mcpToolText(t, ts.URL, access, session, 19, "poll_events", `{"after_seq":`+itoa64(pollPayload.NextSeq)+`,"epoch":"`+pollPayload.Epoch+`"}`)
	if !strings.Contains(poll2, `"count": 0`) && !strings.Contains(poll2, `"count":0`) {
		t.Fatalf("poll_events should be empty after cursor: %s", poll2)
	}

	skillText := mcpToolText(t, ts.URL, access, session, 20, "create_skill", `{"name":"parity-skill","body":"# parity"}`)
	var skillPayload struct {
		Skill struct {
			ID string `json:"id"`
		} `json:"skill"`
	}
	_ = json.Unmarshal([]byte(skillText), &skillPayload)
	if skillPayload.Skill.ID == "" {
		t.Fatalf("create_skill %s", skillText)
	}
	forked := mcpToolText(t, ts.URL, access, session, 21, "fork_skill", `{"id":"`+skillPayload.Skill.ID+`"}`)
	if !strings.Contains(forked, `"origin": "mutation"`) && !strings.Contains(forked, `"origin":"mutation"`) {
		t.Fatalf("fork_skill %s", forked)
	}

	recText := mcpToolText(t, ts.URL, access, session, 22, "create_recording", `{"body":"note","skill_id":"`+skillPayload.Skill.ID+`"}`)
	var recPayload struct {
		Recording struct {
			ID string `json:"id"`
		} `json:"recording"`
	}
	_ = json.Unmarshal([]byte(recText), &recPayload)
	if recPayload.Recording.ID == "" {
		t.Fatalf("create_recording %s", recText)
	}
	promoted := mcpToolText(t, ts.URL, access, session, 23, "promote_recording", `{"id":"`+recPayload.Recording.ID+`","note":"ok"}`)
	if !strings.Contains(promoted, `"status": "promoted"`) && !strings.Contains(promoted, `"status":"promoted"`) {
		t.Fatalf("promote_recording %s", promoted)
	}

	hygiene := mcpToolText(t, ts.URL, access, session, 24, "hygiene", `{}`)
	if !strings.Contains(hygiene, `"counts"`) {
		t.Fatalf("hygiene %s", hygiene)
	}
	imported := mcpToolText(t, ts.URL, access, session, 25, "import_jobs", `{"jobs":[{"company":"Parity Co","title":"Engineer","status":"discovered"}]}`)
	if !strings.Contains(imported, `"imported": 1`) && !strings.Contains(imported, `"imported":1`) {
		t.Fatalf("import_jobs %s", imported)
	}
	exported := mcpToolText(t, ts.URL, access, session, 26, "export_ledger", `{}`)
	if !strings.Contains(exported, "Parity Co") {
		t.Fatalf("export_ledger %s", exported)
	}

	zipText := mcpToolText(t, ts.URL, access, session, 27, "skills_zip", `{}`)
	var zipPayload struct {
		Base64 string `json:"base64"`
		Bytes  int    `json:"bytes"`
	}
	_ = json.Unmarshal([]byte(zipText), &zipPayload)
	if zipPayload.Bytes < 10 || zipPayload.Base64 == "" {
		t.Fatalf("skills_zip %s", zipText)
	}
	if _, err := base64.StdEncoding.DecodeString(zipPayload.Base64); err != nil {
		t.Fatalf("skills_zip base64: %v", err)
	}

	burn := mcpToolText(t, ts.URL, access, session, 28, "add_token_burn", `{"tool_name":"parity","prompt_tokens":3,"completion_tokens":2,"cost_usd":0.01}`)
	if !strings.Contains(burn, `"tool_name": "parity"`) && !strings.Contains(burn, `"tool_name":"parity"`) {
		t.Fatalf("add_token_burn %s", burn)
	}
	summary := mcpToolText(t, ts.URL, access, session, 29, "token_burn_summary", `{}`)
	if !strings.Contains(summary, `"prompt_tokens": 3`) && !strings.Contains(summary, `"prompt_tokens":3`) {
		t.Fatalf("token_burn_summary %s", summary)
	}

	peerText := mcpToolText(t, ts.URL, access, session, 30, "create_peer", `{"name":"peer-a","url":"https://peer.example/a2a"}`)
	var peerPayload struct {
		Peer struct {
			ID string `json:"id"`
		} `json:"peer"`
	}
	_ = json.Unmarshal([]byte(peerText), &peerPayload)
	if peerPayload.Peer.ID == "" {
		t.Fatalf("create_peer %s", peerText)
	}
	dir := mcpToolText(t, ts.URL, access, session, 31, "a2a_directory", `{}`)
	if !strings.Contains(dir, peerPayload.Peer.ID) {
		t.Fatalf("a2a_directory %s", dir)
	}
	sent := mcpToolText(t, ts.URL, access, session, 32, "send_peer", `{"id":"`+peerPayload.Peer.ID+`","payload":{"hello":true}}`)
	if !strings.Contains(sent, `"state": "submitted"`) && !strings.Contains(sent, `"state":"submitted"`) {
		t.Fatalf("send_peer %s", sent)
	}

	resume := mcpToolText(t, ts.URL, access, session, 33, "get_resume", `{}`)
	if !strings.Contains(resume, `"present": true`) && !strings.Contains(resume, `"present":true`) {
		t.Fatalf("get_resume %s", resume)
	}

	// Bootstrapped invite key can also call MCP tools
	if invitePayload.APIKey != "" {
		init := mcpCall(t, ts.URL, invitePayload.APIKey, "", `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","clientInfo":{"name":"ParityInvite"}}}`)
		invSession := init.Header.Get("Mcp-Session-Id")
		initBody := readBody(init)
		if init.StatusCode != 200 || invSession == "" {
			t.Fatalf("invite key init %d %s", init.StatusCode, initBody)
		}
		who := mcpToolText(t, ts.URL, invitePayload.APIKey, invSession, 2, "whoami", `{}`)
		if !strings.Contains(who, "discovery") {
			t.Fatalf("invite whoami %s", who)
		}
	}
}

func TestRealtimeRecentPollBuffer(t *testing.T) {
	hub := realtime.New()
	if hub.Epoch() == "" {
		t.Fatal("hub epoch missing")
	}
	hub.Publish("acc", "job", map[string]any{"id": "j1"})
	hub.Publish("acc", "message", map[string]any{"id": "m1"})
	all := hub.Recent("acc", 0, 10)
	if len(all) != 2 {
		t.Fatalf("want 2 got %d", len(all))
	}
	after := hub.Recent("acc", all[0].Seq, 10)
	if len(after) != 1 || after[0].Event != "message" {
		t.Fatalf("after cursor %#v", after)
	}
	empty := hub.Recent("acc", all[1].Seq, 10)
	if len(empty) != 0 {
		t.Fatalf("expected empty %#v", empty)
	}
}

func TestMCPCreateInviteRejectsInvalidMode(t *testing.T) {
	ts, _ := parityTestServer(t)
	defer ts.Close()

	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}
	res := postJSON(t, client, ts.URL+"/api/auth/signup", `{"username":"modeadmin","password":"long-enough"}`, "")
	csrf := res.Header.Get("X-CSRF")
	res.Body.Close()
	res = putBody(t, client, ts.URL+"/api/candidate", "text/yaml", readyCandidateYAML, csrf)
	res.Body.Close()

	access, session := mcpOAuthSession(t, client, ts.URL, csrf)

	errText, isErr := mcpToolResult(t, ts.URL, access, session, 1, "create_invite", `{"track":"discovery","mode":"not_a_real_mode","mcp_bootstrap":true}`)
	if !isErr {
		t.Fatalf("expected invalid mode rejection, got %s", errText)
	}
	if !strings.Contains(errText, "mode must be") {
		t.Fatalf("unexpected error text: %s", errText)
	}

	okText, isErr := mcpToolResult(t, ts.URL, access, session, 2, "create_invite", `{"track":"discovery","mcp_bootstrap":false}`)
	if isErr {
		t.Fatalf("omitted mode should default: %s", okText)
	}
	if !strings.Contains(okText, `"mode": "owner_then_agents"`) && !strings.Contains(okText, `"mode":"owner_then_agents"`) {
		t.Fatalf("default mode missing: %s", okText)
	}
}

func TestMCPPollEventsResetsStaleCursor(t *testing.T) {
	ts, _ := parityTestServer(t)
	defer ts.Close()

	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}
	res := postJSON(t, client, ts.URL+"/api/auth/signup", `{"username":"polladmin","password":"long-enough"}`, "")
	csrf := res.Header.Get("X-CSRF")
	res.Body.Close()
	res = putBody(t, client, ts.URL+"/api/candidate", "text/yaml", readyCandidateYAML, csrf)
	res.Body.Close()

	access, session := mcpOAuthSession(t, client, ts.URL, csrf)
	_ = mcpToolText(t, ts.URL, access, session, 1, "create_message", `{"body":"poll-reset","to_track":"discovery"}`)

	stale := mcpToolText(t, ts.URL, access, session, 2, "poll_events", `{"after_seq":999999}`)
	var stalePayload struct {
		Count        int    `json:"count"`
		CursorReset  bool   `json:"cursor_reset"`
		Epoch        string `json:"epoch"`
		NextSeq      int64  `json:"next_seq"`
	}
	if err := json.Unmarshal([]byte(stale), &stalePayload); err != nil {
		t.Fatalf("decode stale poll %v %s", err, stale)
	}
	if !stalePayload.CursorReset || stalePayload.Count < 1 || stalePayload.Epoch == "" {
		t.Fatalf("expected cursor reset with events: %#v %s", stalePayload, stale)
	}

	wrongEpoch := mcpToolText(t, ts.URL, access, session, 3, "poll_events", `{"after_seq":`+itoa64(stalePayload.NextSeq)+`,"epoch":"deadbeef"}`)
	var wrongPayload struct {
		Count       int  `json:"count"`
		CursorReset bool `json:"cursor_reset"`
	}
	_ = json.Unmarshal([]byte(wrongEpoch), &wrongPayload)
	if !wrongPayload.CursorReset || wrongPayload.Count < 1 {
		t.Fatalf("expected epoch mismatch reset: %#v %s", wrongPayload, wrongEpoch)
	}

	ok := mcpToolText(t, ts.URL, access, session, 4, "poll_events", `{"after_seq":`+itoa64(stalePayload.NextSeq)+`,"epoch":"`+stalePayload.Epoch+`"}`)
	if !strings.Contains(ok, `"count": 0`) && !strings.Contains(ok, `"count":0`) {
		t.Fatalf("matching epoch should not reset: %s", ok)
	}
	if strings.Contains(ok, `"cursor_reset": true`) || strings.Contains(ok, `"cursor_reset":true`) {
		t.Fatalf("matching epoch should not set cursor_reset: %s", ok)
	}
}

func TestMCPSkillVisibilityStopEventsAndMemoryPods(t *testing.T) {
	ts, _ := parityTestServer(t)
	defer ts.Close()

	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}
	res := postJSON(t, client, ts.URL+"/api/auth/signup", `{"username":"p2admin","password":"long-enough"}`, "")
	csrf := res.Header.Get("X-CSRF")
	res.Body.Close()
	res = putBody(t, client, ts.URL+"/api/candidate", "text/yaml", readyCandidateYAML, csrf)
	res.Body.Close()

	access, session := mcpOAuthSession(t, client, ts.URL, csrf)

	whoAdmin := mcpToolText(t, ts.URL, access, session, 1, "whoami", `{}`)
	var adminWho struct {
		UserID string `json:"user_id"`
	}
	if err := json.Unmarshal([]byte(whoAdmin), &adminWho); err != nil || adminWho.UserID == "" {
		t.Fatalf("admin whoami %s", whoAdmin)
	}

	agentAText := mcpToolText(t, ts.URL, access, session, 2, "create_agent", `{"display_name":"p2-bot-a","track":"discovery"}`)
	var agentA struct {
		APIKey string `json:"api_key"`
		User   struct {
			ID string `json:"id"`
		} `json:"user"`
	}
	if err := json.Unmarshal([]byte(agentAText), &agentA); err != nil || agentA.APIKey == "" || agentA.User.ID == "" {
		t.Fatalf("create_agent A %s", agentAText)
	}
	agentBText := mcpToolText(t, ts.URL, access, session, 3, "create_agent", `{"display_name":"p2-bot-b","track":"discovery"}`)
	var agentB struct {
		APIKey string `json:"api_key"`
		User   struct {
			ID string `json:"id"`
		} `json:"user"`
	}
	if err := json.Unmarshal([]byte(agentBText), &agentB); err != nil || agentB.APIKey == "" || agentB.User.ID == "" {
		t.Fatalf("create_agent B %s", agentBText)
	}

	aSession := mcpAPIKeySession(t, ts.URL, agentA.APIKey)
	bSession := mcpAPIKeySession(t, ts.URL, agentB.APIKey)

	skillText := mcpToolText(t, ts.URL, agentA.APIKey, aSession, 10, "create_skill", `{"name":"bot-a-private","body":"# private local skill for bot A"}`)
	var skillPayload struct {
		Skill struct {
			ID string `json:"id"`
		} `json:"skill"`
	}
	if err := json.Unmarshal([]byte(skillText), &skillPayload); err != nil || skillPayload.Skill.ID == "" {
		t.Fatalf("create_skill %s", skillText)
	}

	listedB := mcpToolText(t, ts.URL, agentB.APIKey, bSession, 11, "list_skills", `{}`)
	if strings.Contains(listedB, skillPayload.Skill.ID) || strings.Contains(listedB, "bot-a-private") {
		t.Fatalf("list_skills leaked another bot local skill: %s", listedB)
	}
	_, getErr := mcpToolResult(t, ts.URL, agentB.APIKey, bSession, 12, "get_skill", `{"id":"`+skillPayload.Skill.ID+`"}`)
	if !getErr {
		t.Fatalf("get_skill should hide another bot local skill")
	}
	listedA := mcpToolText(t, ts.URL, agentA.APIKey, aSession, 13, "list_skills", `{}`)
	if !strings.Contains(listedA, skillPayload.Skill.ID) {
		t.Fatalf("owner should see own local skill: %s", listedA)
	}

	imported := mcpToolText(t, ts.URL, access, session, 20, "import_jobs", `{"jobs":[{"id":"p2-stop-job","company":"P2 Co","title":"Engineer","status":"discovered"}]}`)
	if !strings.Contains(imported, `"imported": 1`) && !strings.Contains(imported, `"imported":1`) {
		t.Fatalf("import_jobs %s", imported)
	}
	stopped := mcpToolText(t, ts.URL, access, session, 21, "stop_job", `{"id":"p2-stop-job","reason":"p2-audit"}`)
	if !strings.Contains(stopped, `"stopped": true`) && !strings.Contains(stopped, `"stopped":true`) {
		t.Fatalf("stop_job %s", stopped)
	}
	events := mcpToolText(t, ts.URL, access, session, 22, "list_events", `{"job_id":"p2-stop-job"}`)
	if !strings.Contains(events, `"action": "stop"`) && !strings.Contains(events, `"action":"stop"`) {
		t.Fatalf("list_events missing stop event: %s", events)
	}
	if !strings.Contains(events, "p2-audit") {
		t.Fatalf("list_events missing stop reason: %s", events)
	}
	resumed := mcpToolText(t, ts.URL, access, session, 23, "resume_job", `{"id":"p2-stop-job"}`)
	if !strings.Contains(resumed, `"stopped": false`) && !strings.Contains(resumed, `"stopped":false`) {
		t.Fatalf("resume_job %s", resumed)
	}
	events2 := mcpToolText(t, ts.URL, access, session, 24, "list_events", `{"job_id":"p2-stop-job"}`)
	if !strings.Contains(events2, `"action": "resume"`) && !strings.Contains(events2, `"action":"resume"`) {
		t.Fatalf("list_events missing resume event: %s", events2)
	}

	memText := mcpToolText(t, ts.URL, access, session, 30, "write_memory", `{"kind":"working_note","title":"admin worker note","body":"private admin worker memory for pod visibility checks","pod":"worker:`+adminWho.UserID+`"}`)
	var memPayload struct {
		Item struct {
			ID string `json:"id"`
		} `json:"item"`
	}
	if err := json.Unmarshal([]byte(memText), &memPayload); err != nil || memPayload.Item.ID == "" {
		t.Fatalf("write_memory %s", memText)
	}
	_, delErr := mcpToolResult(t, ts.URL, agentB.APIKey, bSession, 31, "delete_memory", `{"id":"`+memPayload.Item.ID+`"}`)
	if !delErr {
		t.Fatalf("delete_memory should reject unread pod")
	}
	_, solErr := mcpToolResult(t, ts.URL, agentB.APIKey, bSession, 32, "solidify_memory", `{"id":"`+memPayload.Item.ID+`"}`)
	if !solErr {
		t.Fatalf("solidify_memory should reject unread pod")
	}
	deleted := mcpToolText(t, ts.URL, access, session, 33, "delete_memory", `{"id":"`+memPayload.Item.ID+`"}`)
	if !strings.Contains(deleted, `"ok": true`) && !strings.Contains(deleted, `"ok":true`) {
		t.Fatalf("admin delete_memory %s", deleted)
	}
}

func parityTestServer(t *testing.T) (*httptest.Server, string) {
	t.Helper()
	telemetry.Init(telemetry.Options{Exporter: "none", ServiceName: "jobos-hub-test"})
	root := findRepoRoot(t)
	srv := New(config.Config{RepoRoot: root}, store.NewMemory(), blob.NewMemory(), cache.NewMemory(), realtime.New())
	if n := srv.Seed(context.Background()); n < 5 {
		t.Fatalf("seeded %d", n)
	}
	return httptest.NewServer(srv.Router()), root
}

func findRepoRoot(t *testing.T) string {
	t.Helper()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	dir := wd
	for i := 0; i < 8; i++ {
		if _, err := os.Stat(filepath.Join(dir, "skills", "job-discovery")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	t.Fatalf("repo root not found from %s", wd)
	return ""
}

func mcpOAuthSession(t *testing.T, client *http.Client, base, csrf string) (access, session string) {
	t.Helper()
	res := postJSON(t, client, base+"/oauth/register", `{"client_name":"Parity","redirect_uris":["http://127.0.0.1:9/cb"],"token_endpoint_auth_method":"none"}`, "")
	body := readBody(res)
	var registered map[string]any
	_ = json.Unmarshal([]byte(body), &registered)
	clientID := registered["client_id"].(string)
	verifier := strings.Repeat("b", 64)
	challenge := agentflow.PKCSES256(verifier)
	approve := `{"client_id":"` + clientID + `","redirect_uri":"http://127.0.0.1:9/cb","code_challenge":"` + challenge + `","code_challenge_method":"S256","state":"st","decision":"approve"}`
	res = postJSON(t, client, base+"/oauth/authorize", approve, csrf)
	body = readBody(res)
	var approved map[string]string
	_ = json.Unmarshal([]byte(body), &approved)
	code := strings.Split(strings.Split(approved["redirect"], "code=")[1], "&")[0]

	formBody := "grant_type=authorization_code&client_id=" + clientID + "&code=" + code + "&redirect_uri=http://127.0.0.1:9/cb&code_verifier=" + verifier
	req, _ := http.NewRequest(http.MethodPost, base+"/oauth/token", strings.NewReader(formBody))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	res, err := client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	body = readBody(res)
	var tok map[string]any
	_ = json.Unmarshal([]byte(body), &tok)
	access = tok["access_token"].(string)

	init := mcpCall(t, base, access, "", `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","clientInfo":{"name":"Parity"}}}`)
	session = init.Header.Get("Mcp-Session-Id")
	initBody := readBody(init)
	if init.StatusCode != 200 || session == "" {
		t.Fatalf("init %d %s", init.StatusCode, initBody)
	}
	return access, session
}

func mcpAPIKeySession(t *testing.T, base, apiKey string) string {
	t.Helper()
	init := mcpCall(t, base, apiKey, "", `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","clientInfo":{"name":"ParityAgent"}}}`)
	session := init.Header.Get("Mcp-Session-Id")
	initBody := readBody(init)
	if init.StatusCode != 200 || session == "" {
		t.Fatalf("api key init %d %s", init.StatusCode, initBody)
	}
	return session
}

func mcpToolText(t *testing.T, base, token, session string, id int, name, argsJSON string) string {
	t.Helper()
	text, isErr := mcpToolResult(t, base, token, session, id, name, argsJSON)
	if isErr {
		t.Fatalf("%s error response %s", name, text)
	}
	return text
}

func mcpToolResult(t *testing.T, base, token, session string, id int, name, argsJSON string) (text string, isError bool) {
	t.Helper()
	payload := `{"jsonrpc":"2.0","id":` + itoa(id) + `,"method":"tools/call","params":{"name":"` + name + `","arguments":` + argsJSON + `}}`
	res := mcpCall(t, base, token, session, payload)
	body := readBody(res)
	if res.StatusCode != 200 {
		t.Fatalf("%s status %d %s", name, res.StatusCode, body)
	}
	var envelope struct {
		Result struct {
			IsError bool `json:"isError"`
			Content []struct {
				Text string `json:"text"`
			} `json:"content"`
		} `json:"result"`
		Error any `json:"error"`
	}
	if err := json.Unmarshal([]byte(body), &envelope); err != nil {
		t.Fatalf("%s decode %v %s", name, err, body)
	}
	if len(envelope.Result.Content) == 0 {
		t.Fatalf("%s empty content %s", name, body)
	}
	text = envelope.Result.Content[0].Text
	if envelope.Error != nil || envelope.Result.IsError {
		return text, true
	}
	return text, false
}

func itoa(n int) string { return strconv.Itoa(n) }

func itoa64(n int64) string { return strconv.FormatInt(n, 10) }
