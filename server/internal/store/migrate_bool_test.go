package store

import (
	"os"
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

func TestMigrateOrdersBoolCoerceBeforeSkillsUniqueIndex(t *testing.T) {
	// Source-order guard: coerce must run before skills_id_uidx so a 23505
	// cannot leave allow_multiple_owners as int4.
	data, err := os.ReadFile("postgres.go")
	if err != nil {
		t.Fatal(err)
	}
	src := string(data)
	coerceAt := strings.Index(src, `coerceIntBoolSQL("invites", "allow_multiple_owners")`)
	indexAt := strings.Index(src, `skills_id_uidx`)
	if coerceAt < 0 || indexAt < 0 {
		t.Fatal("missing coerce or skills_id_uidx marker")
	}
	if coerceAt > indexAt {
		t.Fatalf("coerceIntBoolSQL(invites) must appear before skills_id_uidx (coerce=%d index=%d)", coerceAt, indexAt)
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
