package store

import (
	"errors"
	"fmt"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5/pgconn"
)

func TestRemapDuplicateIDSQLSkillsPreservesTenants(t *testing.T) {
	sql := remapDuplicateIDSQL("skills")
	for _, needle := range []string{
		"UPDATE skills",
		"PARTITION BY id",
		"status = 'approved'",
		"scope = 'shared'",
		"account_id || ':' || id",
		"UPDATE skill_recordings",
		"WHERE rn > 1",
	} {
		if !strings.Contains(sql, needle) {
			t.Fatalf("missing %q in:\n%s", needle, sql)
		}
	}
	if strings.Contains(sql, "DELETE FROM skills") {
		t.Fatal("skills remap must not delete tenant rows")
	}
}

func TestRemapDuplicateIDSQLRecordings(t *testing.T) {
	sql := remapDuplicateIDSQL("skill_recordings")
	for _, needle := range []string{
		"UPDATE skill_recordings",
		"PARTITION BY id",
		"account_id || ':' || id",
		"WHERE rn > 1",
	} {
		if !strings.Contains(sql, needle) {
			t.Fatalf("missing %q in:\n%s", needle, sql)
		}
	}
	if strings.Contains(sql, "DELETE FROM skill_recordings") {
		t.Fatal("recording remap must not delete rows")
	}
}

func TestRetryableOpenErrorOnlyTransient(t *testing.T) {
	if RetryableOpenError(fmt.Errorf("migrate: %w", &pgconn.PgError{Code: "23505"})) {
		t.Fatal("unique violation must not retry")
	}
	if RetryableOpenError(&pgconn.PgError{Code: "42501", Message: "permission denied"}) {
		t.Fatal("permission denied must not retry")
	}
	if !RetryableOpenError(&pgconn.PgError{Code: "08006", Message: "connection failure"}) {
		t.Fatal("connection class 08xxx should retry")
	}
	if !RetryableOpenError(errors.New("dial tcp: connection refused")) {
		t.Fatal("connectivity errors should retry")
	}
	if RetryableOpenError(nil) {
		t.Fatal("nil is not retryable")
	}
}
