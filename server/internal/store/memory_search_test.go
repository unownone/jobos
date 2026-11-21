package store

import (
	"strings"
	"testing"
)

func TestMemoryFTSMatchesPythonTokens(t *testing.T) {
	if got := MemoryFTS("Greenhouse work-auth"); got != "greenhouse & work & auth" {
		t.Fatalf("fts %q", got)
	}
	if got := MemoryFTS("???"); got != "" {
		t.Fatalf("punctuation should not filter, got %q", got)
	}
	sql, args := memorySearchSQL(MemoryQuery{
		AccountID: "acc", Now: "2026-01-01T00:00:00Z", Q: "Greenhouse work-auth", Pods: []string{"common"}, Limit: 12,
	})
	if !strings.Contains(sql, "to_tsvector('simple'") || !strings.Contains(sql, "to_tsquery('simple'") || !strings.Contains(sql, "pod = ANY(") {
		t.Fatalf("sql %s", sql)
	}
	if args[len(args)-2] != "greenhouse & work & auth" {
		t.Fatalf("tsquery arg %#v", args)
	}
}
