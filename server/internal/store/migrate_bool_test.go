package store

import (
	"strings"
	"testing"
)

func TestCoerceIntBoolSQLTargetsPythonColumns(t *testing.T) {
	sql := coerceIntBoolSQL("invites", "allow_multiple_owners")
	for _, needle := range []string{
		"table_name = 'invites'",
		"column_name = 'allow_multiple_owners'",
		"data_type IN ('integer', 'smallint', 'bigint')",
		"TYPE BOOLEAN USING",
		"SET DEFAULT FALSE",
	} {
		if !strings.Contains(sql, needle) {
			t.Fatalf("missing %q in:\n%s", needle, sql)
		}
	}
	if strings.Contains(sql, "%%") {
		t.Fatalf("sprintf left doubled percent: %s", sql)
	}
}

func TestCopyColumnIfPresentSQLRenamesPythonBody(t *testing.T) {
	sql := copyColumnIfPresentSQL("skills", "body_md", "body")
	for _, needle := range []string{
		"table_name = 'skills'",
		"column_name = 'body_md'",
		"column_name = 'body'",
		"UPDATE",
	} {
		if !strings.Contains(sql, needle) {
			t.Fatalf("missing %q in:\n%s", needle, sql)
		}
	}
}

func TestDropNotNullIfPresentSQLRelaxesLegacyColumns(t *testing.T) {
	sql := dropNotNullIfPresentSQL("skills", "content_hash")
	for _, needle := range []string{
		"table_name = 'skills'",
		"column_name = 'content_hash'",
		"is_nullable = 'NO'",
		"DROP NOT NULL",
		"SET DEFAULT",
	} {
		if !strings.Contains(sql, needle) {
			t.Fatalf("missing %q in:\n%s", needle, sql)
		}
	}
}
