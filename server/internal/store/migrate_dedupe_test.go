package store

import (
	"errors"
	"fmt"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5/pgconn"
)

func TestDedupeByIDSQLSkillsKeepsPreferredRow(t *testing.T) {
	sql := dedupeByIDSQL("skills")
	for _, needle := range []string{
		"DELETE FROM skills",
		"PARTITION BY id",
		"status = 'approved'",
		"scope = 'shared'",
		"version DESC",
		"WHERE rn > 1",
	} {
		if !strings.Contains(sql, needle) {
			t.Fatalf("missing %q in:\n%s", needle, sql)
		}
	}
}

func TestDedupeByIDSQLRecordings(t *testing.T) {
	sql := dedupeByIDSQL("skill_recordings")
	for _, needle := range []string{
		"DELETE FROM skill_recordings",
		"PARTITION BY id",
		"created_at DESC",
		"WHERE rn > 1",
	} {
		if !strings.Contains(sql, needle) {
			t.Fatalf("missing %q in:\n%s", needle, sql)
		}
	}
}

func TestRetryableOpenErrorSkipsUniqueViolation(t *testing.T) {
	err := fmt.Errorf("migrate: %w", &pgconn.PgError{Code: "23505", Message: "could not create unique index"})
	if RetryableOpenError(err) {
		t.Fatal("unique violation during migrate must not retry")
	}
	if !RetryableOpenError(errors.New("dial tcp: connection refused")) {
		t.Fatal("connectivity errors should retry")
	}
	if RetryableOpenError(nil) {
		t.Fatal("nil is not retryable")
	}
}
