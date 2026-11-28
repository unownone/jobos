package store

import (
	"context"
	"fmt"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

func postgresTestURL(t *testing.T) string {
	t.Helper()
	raw := strings.TrimSpace(os.Getenv("DATABASE_URL"))
	if raw == "" {
		t.Skip("DATABASE_URL not set")
	}
	if !postgresURLAllowsSchemaMutation(raw) {
		t.Skip("DATABASE_URL is not a local/test database; set JOBOS_ALLOW_DESTRUCTIVE_PG_TESTS=1 to override")
	}
	return raw
}

// postgresURLAllowsSchemaMutation gates fixture tests away from shared/prod URLs.
func postgresURLAllowsSchemaMutation(raw string) bool {
	if os.Getenv("JOBOS_ALLOW_DESTRUCTIVE_PG_TESTS") == "1" {
		return true
	}
	u, err := url.Parse(raw)
	if err != nil {
		return false
	}
	host := strings.ToLower(u.Hostname())
	if host != "127.0.0.1" && host != "localhost" && host != "::1" {
		return false
	}
	dbName := strings.TrimPrefix(u.Path, "/")
	if i := strings.IndexByte(dbName, '?'); i >= 0 {
		dbName = dbName[:i]
	}
	dbName = strings.ToLower(dbName)
	return dbName == "jobos" || strings.HasSuffix(dbName, "_test") || strings.HasPrefix(dbName, "jobos_test")
}

// openIsolatedPostgres creates a disposable schema and a pool whose search_path
// is pinned to it, so Migrate/ALTER never touch public (or other shared) objects.
func openIsolatedPostgres(t *testing.T, raw string) *Postgres {
	t.Helper()
	ctx := context.Background()
	schema := fmt.Sprintf("jobos_invite_test_%d", time.Now().UnixNano())
	ident := pgx.Identifier{schema}.Sanitize()

	boot, err := pgxpool.New(ctx, raw)
	if err != nil {
		t.Fatalf("boot pool: %v", err)
	}
	if _, err := boot.Exec(ctx, `CREATE SCHEMA `+ident); err != nil {
		boot.Close()
		t.Fatalf("create schema: %v", err)
	}
	boot.Close()

	cfg, err := pgxpool.ParseConfig(raw)
	if err != nil {
		t.Fatalf("parse config: %v", err)
	}
	cfg.AfterConnect = func(ctx context.Context, conn *pgx.Conn) error {
		_, err := conn.Exec(ctx, `SET search_path TO `+ident)
		return err
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatalf("isolated pool: %v", err)
	}
	p := &Postgres{pool: pool}
	t.Cleanup(func() {
		p.Close()
		cleanup, err := pgxpool.New(context.Background(), raw)
		if err != nil {
			return
		}
		defer cleanup.Close()
		_, _ = cleanup.Exec(context.Background(), `DROP SCHEMA IF EXISTS `+ident+` CASCADE`)
	})
	return p
}

func forceInvitesAllowMultipleOwnersInteger(t *testing.T, p *Postgres) {
	t.Helper()
	ctx := context.Background()
	if err := p.Migrate(ctx); err != nil {
		t.Fatalf("migrate before int4 fixture: %v", err)
	}
	_, err := p.pool.Exec(ctx, `
		ALTER TABLE invites ALTER COLUMN allow_multiple_owners DROP DEFAULT;
		ALTER TABLE invites ALTER COLUMN allow_multiple_owners TYPE INTEGER
			USING (CASE WHEN allow_multiple_owners THEN 1 ELSE 0 END);
		ALTER TABLE invites ALTER COLUMN allow_multiple_owners SET DEFAULT 0;
	`)
	if err != nil {
		t.Fatalf("force int4 fixture: %v", err)
	}
}

func TestCreateInviteWorksOnPythonEraIntegerColumn(t *testing.T) {
	raw := postgresTestURL(t)
	ctx := context.Background()
	p := openIsolatedPostgres(t, raw)
	forceInvitesAllowMultipleOwnersInteger(t, p)

	dt, udt, err := p.columnType(ctx, "invites", "allow_multiple_owners")
	if err != nil {
		t.Fatal(err)
	}
	if dt != "integer" || udt != "int4" {
		t.Fatalf("fixture want integer/int4, got %s/%s", dt, udt)
	}

	suffix := time.Now().UnixNano()
	idFalse := fmt.Sprintf("inv_int4_ok_%d", suffix)
	idTrue := fmt.Sprintf("inv_int4_true_%d", suffix)
	inv := Invite{
		ID: idFalse, AccountID: "acc1", Track: "discovery", Mode: "owner_then_agents",
		SecretHash: "hash", MaxRedemptions: 5, Redemptions: 0,
		ExpiresAt: time.Now().UTC().Add(72 * time.Hour).Format(time.RFC3339),
		RevokedAt: "", CreatedBy: "user1", AllowMultipleOwners: false,
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
	}
	if err := p.CreateInvite(ctx, inv); err != nil {
		t.Fatalf("CreateInvite against INTEGER column: %v", err)
	}
	got, err := p.Invite(ctx, inv.ID)
	if err != nil {
		t.Fatalf("Invite scan: %v", err)
	}
	if got.AllowMultipleOwners {
		t.Fatalf("want allow_multiple_owners=false, got true")
	}

	inv.ID = idTrue
	inv.AllowMultipleOwners = true
	if err := p.CreateInvite(ctx, inv); err != nil {
		t.Fatalf("CreateInvite true against INTEGER: %v", err)
	}
	got, err = p.Invite(ctx, inv.ID)
	if err != nil || !got.AllowMultipleOwners {
		t.Fatalf("want true, got allow=%v err=%v", got.AllowMultipleOwners, err)
	}
}

func TestMigrateCoercesInviteBoolBeforeUniqueIndex(t *testing.T) {
	raw := postgresTestURL(t)
	ctx := context.Background()
	p := openIsolatedPostgres(t, raw)
	forceInvitesAllowMultipleOwnersInteger(t, p)

	pre, _, err := p.columnType(ctx, "invites", "allow_multiple_owners")
	if err != nil {
		t.Fatal(err)
	}
	if pre != "integer" {
		t.Fatalf("pre-migrate want integer, got %s", pre)
	}
	if err := p.Migrate(ctx); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	post, udt, err := p.columnType(ctx, "invites", "allow_multiple_owners")
	if err != nil {
		t.Fatal(err)
	}
	if post != "boolean" || udt != "bool" {
		t.Fatalf("post-migrate want boolean/bool, got %s/%s", post, udt)
	}
	id := fmt.Sprintf("inv_after_migrate_%d", time.Now().UnixNano())
	inv := Invite{
		ID: id, AccountID: "acc1", Track: "discovery", Mode: "owner_then_agents",
		SecretHash: "hash", MaxRedemptions: 5,
		ExpiresAt: time.Now().UTC().Add(72 * time.Hour).Format(time.RFC3339),
		CreatedBy: "user1", AllowMultipleOwners: false,
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
	}
	if err := p.CreateInvite(ctx, inv); err != nil {
		t.Fatalf("CreateInvite after migrate: %v", err)
	}
}

func TestRequireSchemaRejectsIntegerInviteFlag(t *testing.T) {
	raw := postgresTestURL(t)
	ctx := context.Background()
	p := openIsolatedPostgres(t, raw)
	forceInvitesAllowMultipleOwnersInteger(t, p)
	err := p.RequireSchema(ctx)
	if err == nil || !strings.Contains(err.Error(), "allow_multiple_owners") || !strings.Contains(err.Error(), "hub migrate") {
		t.Fatalf("want RequireSchema drift error, got %v", err)
	}
}

func TestPostgresURLAllowsSchemaMutationGuard(t *testing.T) {
	t.Setenv("JOBOS_ALLOW_DESTRUCTIVE_PG_TESTS", "")
	if postgresURLAllowsSchemaMutation("postgres://u:p@db.example.com:5432/jobos") {
		t.Fatal("remote host must be rejected")
	}
	if !postgresURLAllowsSchemaMutation("postgres://jobos:jobos@127.0.0.1:5432/jobos?sslmode=disable") {
		t.Fatal("local jobos must be allowed")
	}
	if !postgresURLAllowsSchemaMutation("postgres://u:p@localhost/jobos_test") {
		t.Fatal("local *_test must be allowed")
	}
	t.Setenv("JOBOS_ALLOW_DESTRUCTIVE_PG_TESTS", "1")
	if !postgresURLAllowsSchemaMutation("postgres://u:p@db.example.com:5432/prod") {
		t.Fatal("explicit override must allow")
	}
}
