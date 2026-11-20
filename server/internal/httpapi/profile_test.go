package httpapi

import "testing"

func TestProfileAcceptsFlatAndNested(t *testing.T) {
	if missing := profileMissing(readyCandidateYAML); missing != "" {
		t.Fatal(missing)
	}
	flat := "name: Grace Hopper\nemail: grace@navy.test\ntitles: Compiler Engineer\nlocations: Remote, Washington\n"
	if missing := profileMissing(flat); missing != "" {
		t.Fatal(missing)
	}
	nested := "" +
		"identity:\n  full_name: Grace Hopper\n  email: grace@navy.test\n" +
		"target:\n  titles:\n    - Compiler Engineer\n  locations:\n    - Remote\n"
	if missing := profileMissing(nested); missing != "" {
		t.Fatal(missing)
	}
	if missing := profileMissing("name: Ada Lovelace\n"); missing != "identity.email, target.titles, target.locations" {
		t.Fatalf("missing %q", missing)
	}
	example := "name: Ada Example\nemail: ada@example.com\ntitles:\n  - Engineer\nlocations:\n  - Remote\n"
	if missing := profileMissing(example); missing == "" {
		t.Fatal("example profile should be rejected")
	}
}
