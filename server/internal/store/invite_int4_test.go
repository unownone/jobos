package store

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"
)

func postgresTestURL(t *testing.T) string {
	t.Helper()
	url := strings.TrimSpace(os.Getenv("DATABASE_URL"))
	if url == "" {
		t.Skip("DATABASE_URL not set")
	}
	return url
}

func resetInvitesIntegerColumn(t *testing.T, p *Postgres) {
	t.Helper()
	ctx := context.Background()
	_, err := p.pool.Exec(ctx, `DROP TABLE IF EXISTS invites CASCADE`)
	if err != nil {
		t.Fatal(err)
	}
	_, err = p.pool.Exec(ctx, `CREATE TABLE invites (
		id TEXT PRIMARY KEY,
		account_id TEXT NOT NULL,
		track TEXT NOT NULL,
		mode TEXT NOT NULL,
		secret_hash TEXT NOT NULL,
		max_redemptions INTEGER NOT NULL,
		redemptions INTEGER NOT NULL DEFAULT 0,
		expires_at TEXT NOT NULL,
		revoked_at TEXT NOT NULL DEFAULT '',
		created_by TEXT NOT NULL DEFAULT '',
		allow_multiple_owners INTEGER NOT NULL DEFAULT 0,
		created_at TEXT NOT NULL
	)`)
	if err != nil {
		t.Fatal(err)
	}
}

func TestCreateInviteWorksOnPythonEraIntegerColumn(t *testing.T) {
	url := postgresTestURL(t)
	ctx := context.Background()
	p, err := OpenPostgres(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer p.Close()
	resetInvitesIntegerColumn(t, p)

	dt, udt := p.columnType(ctx, "invites", "allow_multiple_owners")
	if dt != "integer" || udt != "int4" {
		t.Fatalf("fixture want integer/int4, got %s/%s", dt, udt)
	}

	inv := Invite{
		ID: "inv_int4_ok", AccountID: "acc1", Track: "discovery", Mode: "owner_then_agents",
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

	inv.ID = "inv_int4_true"
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
	url := postgresTestURL(t)
	ctx := context.Background()
	p, err := OpenPostgres(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer p.Close()
	resetInvitesIntegerColumn(t, p)

	pre, _ := p.columnType(ctx, "invites", "allow_multiple_owners")
	if pre != "integer" {
		t.Fatalf("pre-migrate want integer, got %s", pre)
	}
	if err := p.Migrate(ctx); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	post, udt := p.columnType(ctx, "invites", "allow_multiple_owners")
	if post != "boolean" || udt != "bool" {
		t.Fatalf("post-migrate want boolean/bool, got %s/%s", post, udt)
	}
	_, _ = p.pool.Exec(ctx, `DELETE FROM invites WHERE id=$1`, "inv_after_migrate")
	inv := Invite{
		ID: "inv_after_migrate", AccountID: "acc1", Track: "discovery", Mode: "owner_then_agents",
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
	url := postgresTestURL(t)
	ctx := context.Background()
	p, err := OpenPostgres(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer p.Close()

	// Full schema so accounts exists, then force invites flag back to INTEGER.
	if err := p.Migrate(ctx); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	_, err = p.pool.Exec(ctx, `
		ALTER TABLE invites ALTER COLUMN allow_multiple_owners DROP DEFAULT;
		ALTER TABLE invites ALTER COLUMN allow_multiple_owners TYPE INTEGER USING (CASE WHEN allow_multiple_owners THEN 1 ELSE 0 END);
		ALTER TABLE invites ALTER COLUMN allow_multiple_owners SET DEFAULT 0;
	`)
	if err != nil {
		t.Fatalf("force int4: %v", err)
	}
	err = p.RequireSchema(ctx)
	if err == nil || !strings.Contains(err.Error(), "allow_multiple_owners") || !strings.Contains(err.Error(), "hub migrate") {
		t.Fatalf("want RequireSchema drift error, got %v", err)
	}
}
