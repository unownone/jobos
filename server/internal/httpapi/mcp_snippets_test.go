package httpapi

import (
	"strings"
	"testing"
)

func TestBuildMCPClientSnippets(t *testing.T) {
	snippets := BuildMCPClientSnippets("https://ikr.one/", "jh_agt_testkey123")
	if len(snippets) < 4 {
		t.Fatalf("expected cursor/claude/grok/codex, got %d", len(snippets))
	}
	ids := map[string]bool{}
	for _, snip := range snippets {
		ids[snip.ID] = true
		if snip.Config == "" || snip.Label == "" {
			t.Fatalf("empty snippet %#v", snip)
		}
		if !strings.Contains(snip.Config, "https://ikr.one/mcp") {
			t.Fatalf("missing mcp url in %s: %s", snip.ID, snip.Config)
		}
		if !strings.Contains(snip.Config, "jh_agt_testkey123") {
			t.Fatalf("missing api key in %s", snip.ID)
		}
		if !strings.Contains(strings.ToLower(snip.Instruction), "bearer") {
			t.Fatalf("auth instruction missing in %s", snip.ID)
		}
	}
	for _, want := range []string{"cursor", "claude", "grok", "codex"} {
		if !ids[want] {
			t.Fatalf("missing client %s", want)
		}
	}
	codex := snippets[3]
	if codex.Format != "toml" || !strings.Contains(codex.Config, "[mcp_servers.jobos]") {
		t.Fatalf("codex toml %#v", codex)
	}
}

func TestToolCatalogCoversParitySurface(t *testing.T) {
	tools := toolCatalog()
	names := map[string]bool{}
	for _, tool := range tools {
		name, _ := tool["name"].(string)
		names[name] = true
	}
	required := []string{
		"get_started", "list_jobs", "create_job", "update_job", "delete_job",
		"queue_push", "queue_claim", "queue_ack", "queue_nack", "queue_mine", "queue_list",
		"recall_memory", "write_memory", "delete_memory", "solidify_memory",
		"get_candidate", "candidate_status", "list_skills", "list_mcps",
		"list_people", "create_person", "list_events", "heartbeat", "whoami",
	}
	for _, name := range required {
		if !names[name] {
			t.Fatalf("missing tool %s", name)
		}
	}
}
