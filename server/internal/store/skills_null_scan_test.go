package store

import (
	"context"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"
)

// stubRow implements pgx.Row for scan unit tests without a live database.
type stubRow struct {
	vals []any
	err  error
}

func (r stubRow) Scan(dest ...any) error {
	if r.err != nil {
		return r.err
	}
	if len(dest) != len(r.vals) {
		return fmt.Errorf("scan arity: got %d want %d", len(dest), len(r.vals))
	}
	for i, d := range dest {
		if err := assignStub(d, r.vals[i]); err != nil {
			return fmt.Errorf("can't scan into dest[%d]: %w", i, err)
		}
	}
	return nil
}

func assignStub(dest, src any) error {
	switch d := dest.(type) {
	case *string:
		if src == nil {
			return fmt.Errorf("cannot scan NULL into *string")
		}
		s, ok := src.(string)
		if !ok {
			return fmt.Errorf("want string, got %T", src)
		}
		*d = s
		return nil
	case **string:
		if src == nil {
			*d = nil
			return nil
		}
		s, ok := src.(string)
		if !ok {
			return fmt.Errorf("want string, got %T", src)
		}
		*d = &s
		return nil
	case *int:
		if src == nil {
			return fmt.Errorf("cannot scan NULL into *int")
		}
		n, ok := src.(int)
		if !ok {
			return fmt.Errorf("want int, got %T", src)
		}
		*d = n
		return nil
	case **int:
		if src == nil {
			*d = nil
			return nil
		}
		n, ok := src.(int)
		if !ok {
			return fmt.Errorf("want int, got %T", src)
		}
		*d = &n
		return nil
	default:
		return fmt.Errorf("unsupported dest %T", dest)
	}
}

func TestScanSkillNullOwnerUserID(t *testing.T) {
	// Column order matches skillSelect / scanSkill. dest[8] is owner_user_id —
	// the Skills & MCPs page failed with: cannot scan NULL into *string.
	row := stubRow{vals: []any{
		"sk_1", "shared", "demo-skill", "Demo", "skill", "discovery", `["source"]`, "shared",
		nil, // owner_user_id NULL
		"approved", "cursor", "# body", "seed", 1, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
	}}
	s, err := scanSkill(row)
	if err != nil {
		t.Fatalf("scanSkill with NULL owner_user_id: %v", err)
	}
	if s.OwnerID != "" {
		t.Fatalf("OwnerID=%q, want empty", s.OwnerID)
	}
	if s.Slug != "demo-skill" || s.Status != "approved" {
		t.Fatalf("unexpected skill: %+v", s)
	}
}

func TestScanSkillNullSoftColumns(t *testing.T) {
	row := stubRow{vals: []any{
		"sk_2", nil, nil, nil, nil, nil, nil, nil,
		nil, nil, nil, nil, nil, nil, nil, nil,
	}}
	s, err := scanSkill(row)
	if err != nil {
		t.Fatalf("scanSkill with all soft NULLs: %v", err)
	}
	if s.ID != "sk_2" {
		t.Fatalf("id=%q", s.ID)
	}
	if s.Kind != "skill" || s.Scope != "shared" || s.Status != "approved" || s.Version != 1 {
		t.Fatalf("defaults not applied: %+v", s)
	}
	if string(s.Tags) != "[]" {
		t.Fatalf("tags=%q", s.Tags)
	}
}

func TestSkillSelectCoalescesOwnerUserID(t *testing.T) {
	if !strings.Contains(skillSelect, "coalesce(owner_user_id,'')") {
		t.Fatalf("skillSelect must coalesce owner_user_id; got:\n%s", skillSelect)
	}
}

func TestScanMCPNullPlatformsAndSource(t *testing.T) {
	// dest[8] on mcpSelect is platforms_json; source/install/auth/notes follow.
	row := stubRow{vals: []any{
		"shared", "mcp_1", "exa", "Exa", "mcp", "adopted",
		`["search"]`, `["discovery"]`, nil, // platforms_json NULL
		nil, nil, nil, nil, // source, install, auth, notes
		"github", "t0", "t1",
	}}
	item, err := scanMCP(row)
	if err != nil {
		t.Fatalf("scanMCP with NULL platforms/source: %v", err)
	}
	if string(item.Platforms) != "[]" {
		t.Fatalf("platforms=%q", item.Platforms)
	}
	if item.Source != "" || item.Install != "" {
		t.Fatalf("expected empty source/install, got %+v", item)
	}
}

func TestListSkillsPostgresNullOwner(t *testing.T) {
	url := strings.TrimSpace(os.Getenv("DATABASE_URL"))
	if url == "" {
		t.Skip("DATABASE_URL not set")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	p, err := OpenPostgres(ctx, url)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer p.Close()
	if err := p.Migrate(ctx); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	// Migrate creates owner_user_id as NOT NULL. Production still has legacy
	// nullable columns from older schemas (ADD COLUMN IF NOT EXISTS is a no-op
	// when the column already exists nullable). Relax the constraint so this
	// test can insert the NULL row the coalesce scan path must tolerate.
	_, err = p.pool.Exec(ctx, `ALTER TABLE skills ALTER COLUMN owner_user_id DROP NOT NULL`)
	if err != nil {
		t.Fatalf("drop NOT NULL on owner_user_id: %v", err)
	}
	t.Cleanup(func() {
		_, _ = p.pool.Exec(context.Background(), `
			UPDATE skills SET owner_user_id = '' WHERE owner_user_id IS NULL;
			ALTER TABLE skills ALTER COLUMN owner_user_id SET NOT NULL`)
	})
	id := fmt.Sprintf("test_null_owner_%d", time.Now().UnixNano())
	_, err = p.pool.Exec(ctx, `
		INSERT INTO skills (id, account_id, slug, name, kind, role, tags_json, scope, owner_user_id, status, platform, body, origin, version, created_at, updated_at)
		VALUES ($1,'shared',$2,'Null Owner','skill','', '["source"]','shared', NULL, 'approved','','body','test',1,$3,$3)`,
		id, id, time.Now().UTC().Format(time.RFC3339))
	if err != nil {
		t.Fatalf("insert NULL owner_user_id: %v", err)
	}
	t.Cleanup(func() {
		_, _ = p.pool.Exec(context.Background(), `DELETE FROM skills WHERE id=$1`, id)
	})

	rows, err := p.ListSkills(ctx, "shared", "", "", "")
	if err != nil {
		t.Fatalf("ListSkills with NULL owner_user_id row: %v", err)
	}
	found := false
	for _, s := range rows {
		if s.ID == id {
			found = true
			if s.OwnerID != "" {
				t.Fatalf("OwnerID=%q after list", s.OwnerID)
			}
		}
	}
	if !found {
		t.Fatalf("inserted skill %s not returned", id)
	}
}
