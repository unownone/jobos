package agentflow

import (
	"strings"
	"testing"
)

func session(lanes []string, browser, email, reported bool) SessionView {
	return SessionView{Lanes: lanes, Capabilities: Capabilities{Browser: browser, Email: email, Reported: reported}}
}

func TestFindBlocksUntilLanesAndBrowser(t *testing.T) {
	unset := EvaluateLane(session(nil, false, false, false), "find")
	if unset["can"] != false || unset["reason"] != "lanes_unset" || !strings.Contains(unset["instruction"].(string), "Ask the human") {
		t.Fatalf("%#v", unset)
	}
	unreported := EvaluateLane(session([]string{"find", "apply"}, false, false, false), "find")
	if unreported["reason"] != "capabilities_not_reported" {
		t.Fatal(unreported["reason"])
	}
	noBrowser := EvaluateLane(session([]string{"find"}, false, true, true), "find")
	missing, _ := noBrowser["missing"].([]string)
	if noBrowser["can"] != false || len(missing) == 0 || missing[0] != "browser" {
		t.Fatalf("%#v", noBrowser)
	}
	ready := EvaluateLane(session([]string{"find", "outreach"}, true, false, true), "find")
	if ready["can"] != true || ready["skill"] != "job-discovery" {
		t.Fatalf("%#v", ready)
	}
}

func TestApplyNeedsBrowserAndOutreachNeedsEmail(t *testing.T) {
	caps := session([]string{"apply", "outreach"}, true, false, true)
	if EvaluateLane(caps, "apply")["can"] != true {
		t.Fatal("apply")
	}
	outreach := EvaluateLane(caps, "outreach")
	missing := outreach["missing"].([]string)
	if outreach["can"] != false || len(missing) != 1 || missing[0] != "email" {
		t.Fatalf("%#v", outreach)
	}
	outside := EvaluateLane(session([]string{"find"}, true, true, true), "apply")
	if outside["reason"] != "lane_not_in_session" {
		t.Fatal(outside["reason"])
	}
}

func TestFindLoopStopsAtShortlistCap(t *testing.T) {
	jobs := make([]JobView, 12)
	for i := range jobs {
		jobs[i] = JobView{ID: "board", Status: "apply_ready", Sources: []string{"indeed"}, Company: "A", Title: "E"}
	}
	step := PlanLoop(LaneFind, "loop_1", jobs)
	if step["status"] != "done" || step["continue"] != false {
		t.Fatalf("%#v", step)
	}
	running := PlanLoop(LaneFind, "loop_1", jobs[:2])
	if running["continue"] != true || !strings.Contains(running["instruction"].(string), "create_job") {
		t.Fatalf("%#v", running)
	}
}

func TestApplyLoopNamesOneReadyJob(t *testing.T) {
	step := PlanLoop(LaneApply, "", []JobView{{ID: "greenhouse__1", Status: "apply_ready", Company: "Acme", Title: "Staff"}})
	if step["job_id"] != "greenhouse__1" || step["continue"] != true {
		t.Fatalf("%#v", step)
	}
	blocked := PlanLoop(LaneApply, "", nil)
	if blocked["status"] != "blocked" {
		t.Fatal(blocked["status"])
	}
}

func TestPKCEAndRedirect(t *testing.T) {
	if !PKCEVerifierOK(strings.Repeat("a", 64)) || PKCEVerifierOK(strings.Repeat("a", 42)) || PKCEVerifierOK(strings.Repeat("a", 129)) {
		t.Fatal("verifier length")
	}
	if PKCEVerifierOK(strings.Repeat("a", 43) + " ") || PKCEVerifierOK(strings.Repeat("é", 64)) {
		t.Fatal("verifier charset")
	}
	merged := WithQuery("https://client.example/callback?app=jobos&desk=1", map[string]string{"code": "abc", "state": "s1"})
	if !strings.Contains(merged, "app=jobos") || !strings.Contains(merged, "code=abc") || !strings.Contains(merged, "state=s1") {
		t.Fatal(merged)
	}
	if !RedirectURIAllowed("http://127.0.0.1:8787/callback") || !RedirectURIAllowed("https://example.com/oauth") || !RedirectURIAllowed("cursor://anysphere.cursor-mcp/oauth/callback") {
		t.Fatal("allowed")
	}
	if RedirectURIAllowed("http://evil.example/steal") || RedirectURIAllowed("javascript:alert(1)") || RedirectURIAllowed("https://example.com/cb#token") {
		t.Fatal("blocked")
	}
}
