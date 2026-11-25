package store

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Postgres struct {
	pool *pgxpool.Pool
}

func OpenPostgres(ctx context.Context, url string) (*Postgres, error) {
	pool, err := pgxpool.New(ctx, url)
	if err != nil {
		return nil, err
	}
	p := &Postgres{pool: pool}
	if err := p.migrate(ctx); err != nil {
		pool.Close()
		return nil, err
	}
	return p, nil
}

func Open(ctx context.Context, databaseURL string) (Store, error) {
	if strings.TrimSpace(databaseURL) == "" {
		return NewMemory(), nil
	}
	return OpenPostgres(ctx, databaseURL)
}

func (p *Postgres) migrate(ctx context.Context) error {
	if _, err := p.pool.Exec(ctx, schemaSQL); err != nil {
		return err
	}
	for _, stmt := range []string{
		`ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS job_id TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS company TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS pinned BOOLEAN NOT NULL DEFAULT FALSE`,
		`ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS tags_json TEXT NOT NULL DEFAULT '[]'`,
		`CREATE INDEX IF NOT EXISTS memory_items_fts ON memory_items USING GIN (to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(body,'') || ' ' || coalesce(company,'')))`,
		// Python Hub used body_md; Go selects body. CREATE TABLE IF NOT EXISTS
		// does not rename columns on an existing production database.
		`ALTER TABLE skills ADD COLUMN IF NOT EXISTS body TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE skills ADD COLUMN IF NOT EXISTS account_id TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE skills ADD COLUMN IF NOT EXISTS slug TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE skills ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE skills ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'skill'`,
		`ALTER TABLE skills ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE skills ADD COLUMN IF NOT EXISTS tags_json TEXT NOT NULL DEFAULT '[]'`,
		`ALTER TABLE skills ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'shared'`,
		`ALTER TABLE skills ADD COLUMN IF NOT EXISTS owner_user_id TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE skills ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'approved'`,
		`ALTER TABLE skills ADD COLUMN IF NOT EXISTS platform TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE skills ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE skills ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1`,
		`ALTER TABLE skills ADD COLUMN IF NOT EXISTS created_at TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE skills ADD COLUMN IF NOT EXISTS updated_at TEXT NOT NULL DEFAULT ''`,
		copyColumnIfPresentSQL("skills", "body_md", "body"),
		// Go inserts omit Python-era NOT NULL columns; drop the constraint after copy.
		dropNotNullIfPresentSQL("skills", "body_md"),
		dropNotNullIfPresentSQL("skills", "content_hash"),
		`ALTER TABLE skill_recordings ADD COLUMN IF NOT EXISTS body TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE skill_recordings ADD COLUMN IF NOT EXISTS submitter_user_id TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE skill_recordings ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE skill_recordings ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending'`,
		`ALTER TABLE skill_recordings ADD COLUMN IF NOT EXISTS proctor_note TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE skill_recordings ADD COLUMN IF NOT EXISTS created_at TEXT NOT NULL DEFAULT ''`,
		copyColumnIfPresentSQL("skill_recordings", "payload_json", "body"),
		copyColumnIfPresentSQL("skill_recordings", "submitted_by", "submitter_user_id"),
		dropNotNullIfPresentSQL("skill_recordings", "payload_json"),
		dropNotNullIfPresentSQL("skill_recordings", "submitted_by"),
		`ALTER TABLE mcps ADD COLUMN IF NOT EXISTS capability_json TEXT NOT NULL DEFAULT '[]'`,
		`ALTER TABLE mcps ADD COLUMN IF NOT EXISTS roles_json TEXT NOT NULL DEFAULT '[]'`,
		`ALTER TABLE mcps ADD COLUMN IF NOT EXISTS platforms_json TEXT NOT NULL DEFAULT '[]'`,
		`ALTER TABLE mcps ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE mcps ADD COLUMN IF NOT EXISTS install TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE mcps ADD COLUMN IF NOT EXISTS auth TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE mcps ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE mcps ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'github'`,
		`ALTER TABLE mcps ADD COLUMN IF NOT EXISTS created_at TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE mcps ADD COLUMN IF NOT EXISTS updated_at TEXT NOT NULL DEFAULT ''`,
		dropNotNullIfPresentSQL("mcps", "content_hash"),
		// Python PK was (account_id, id), so the same skill id can exist on many
		// accounts. Go upserts ON CONFLICT (id) and needs a single row per id.
		dedupeByIDSQL("skills"),
		dedupeByIDSQL("skill_recordings"),
		`CREATE UNIQUE INDEX IF NOT EXISTS skills_id_uidx ON skills (id)`,
		`CREATE UNIQUE INDEX IF NOT EXISTS skill_recordings_id_uidx ON skill_recordings (id)`,
		// Python Hub stored these as INTEGER 0/1. Go writes bool; pgx cannot encode
		// false into int4. Coerce leftover integer columns on every boot.
		coerceIntBoolSQL("invites", "allow_multiple_owners"),
		coerceIntBoolSQL("jobs", "stopped"),
		coerceIntBoolSQL("people", "do_not_contact"),
		coerceIntBoolSQL("memory_items", "pinned"),
		coerceIntBoolSQL("skills", "reproducible"),
	} {
		if _, err := p.pool.Exec(ctx, stmt); err != nil {
			return fmt.Errorf("migrate: %w", err)
		}
	}
	return nil
}

// coerceIntBoolSQL rewrites a Python-era INTEGER flag column to BOOLEAN.
func coerceIntBoolSQL(table, column string) string {
	return fmt.Sprintf(`
DO $migrate$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = '%s'
      AND column_name = '%s'
      AND data_type IN ('integer', 'smallint', 'bigint')
  ) THEN
    EXECUTE format(
      'ALTER TABLE %%I ALTER COLUMN %%I DROP DEFAULT',
      '%s', '%s'
    );
    EXECUTE format(
      'ALTER TABLE %%I ALTER COLUMN %%I TYPE BOOLEAN USING (COALESCE(%%I, 0) <> 0)',
      '%s', '%s', '%s'
    );
    EXECUTE format(
      'ALTER TABLE %%I ALTER COLUMN %%I SET DEFAULT FALSE',
      '%s', '%s'
    );
  END IF;
END
$migrate$;`, table, column, table, column, table, column, column, table, column)
}

// copyColumnIfPresentSQL copies src into dst when src still exists (Python rename).
func copyColumnIfPresentSQL(table, src, dst string) string {
	return fmt.Sprintf(`
DO $migrate$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = '%s' AND column_name = '%s'
  ) AND EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = '%s' AND column_name = '%s'
  ) THEN
    EXECUTE format(
      'UPDATE %%I SET %%I = %%I WHERE (%%I IS NULL OR %%I::text = '''') AND %%I IS NOT NULL',
      '%s', '%s', '%s', '%s', '%s', '%s'
    );
  END IF;
END
$migrate$;`, table, src, table, dst, table, dst, src, dst, dst, src)
}

// dropNotNullIfPresentSQL lets Go inserts omit Python-era columns.
func dropNotNullIfPresentSQL(table, column string) string {
	return fmt.Sprintf(`
DO $migrate$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = '%s'
      AND column_name = '%s'
      AND is_nullable = 'NO'
  ) THEN
    EXECUTE format('ALTER TABLE %%I ALTER COLUMN %%I DROP NOT NULL', '%s', '%s');
    EXECUTE format('ALTER TABLE %%I ALTER COLUMN %%I SET DEFAULT ''''', '%s', '%s');
  END IF;
END
$migrate$;`, table, column, table, column, table, column)
}

// dedupeByIDSQL drops extra rows that share an id so CREATE UNIQUE INDEX on id
// can succeed on databases upgraded from Python's (account_id, id) primary key.
func dedupeByIDSQL(table string) string {
	orderBy := "ctid ASC"
	switch table {
	case "skills":
		orderBy = `CASE WHEN status = 'approved' THEN 0 ELSE 1 END,
      CASE WHEN scope = 'shared' THEN 0 ELSE 1 END,
      version DESC NULLS LAST,
      updated_at DESC NULLS LAST,
      created_at DESC NULLS LAST,
      ctid ASC`
	case "skill_recordings":
		orderBy = `CASE WHEN status = 'approved' THEN 0 WHEN status = 'pending' THEN 1 ELSE 2 END,
      created_at DESC NULLS LAST,
      ctid ASC`
	default:
		// Keep the helper locked to known tables; callers pass constants only.
	}
	return fmt.Sprintf(`
DELETE FROM %s
WHERE ctid IN (
  SELECT ctid FROM (
    SELECT ctid,
           ROW_NUMBER() OVER (PARTITION BY id ORDER BY %s) AS rn
    FROM %s
  ) ranked
  WHERE rn > 1
);`, table, orderBy, table)
}

// RetryableOpenError is true for transient Postgres connectivity failures.
// Schema conflicts (unique violations during migrate) must not loop until the
// Cloud Run / Railway listen probe times out.
func RetryableOpenError(err error) bool {
	if err == nil {
		return false
	}
	var pg *pgconn.PgError
	if errors.As(err, &pg) {
		switch pg.Code {
		case "23505", "42P07", "42701", "42703", "42P01":
			return false
		default:
			return true
		}
	}
	if strings.Contains(err.Error(), "SQLSTATE 23505") {
		return false
	}
	return true
}

func (p *Postgres) Name() string { return "postgres" }

func (p *Postgres) Ping(ctx context.Context) error { return p.pool.Ping(ctx) }

func (p *Postgres) Close() error {
	p.pool.Close()
	return nil
}

func isUnique(err error) bool {
	var pg *pgconn.PgError
	return errors.As(err, &pg) && pg.Code == "23505"
}

func (p *Postgres) CreateAccount(ctx context.Context, a Account, admin User) error {
	tx, err := p.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	_, err = tx.Exec(ctx, `INSERT INTO accounts (id, username, password_hash, created_at) VALUES ($1,$2,$3,$4)`,
		a.ID, a.Username, a.PasswordHash, a.CreatedAt)
	if err != nil {
		if isUnique(err) {
			return ErrConflict
		}
		return err
	}
	if err := insertUser(ctx, tx, admin); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func insertUser(ctx context.Context, tx pgx.Tx, u User) error {
	_, err := tx.Exec(ctx, `
		INSERT INTO users (id, account_id, kind, track, email, password_hash, display_name, metadata_json, created_by, disabled_at, created_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`,
		u.ID, u.AccountID, u.Kind, u.Track, u.Email, u.PasswordHash, u.DisplayName, rawOr(u.Metadata, "{}"), u.CreatedBy, u.DisabledAt, u.CreatedAt)
	if isUnique(err) {
		return ErrConflict
	}
	return err
}

func rawOr(b []byte, fallback string) string {
	if len(b) == 0 {
		return fallback
	}
	return string(b)
}

func (p *Postgres) AccountByUsername(ctx context.Context, username string) (Account, User, error) {
	a, err := scanAccount(p.pool.QueryRow(ctx, accountSelect+` WHERE lower(username)=lower($1)`, username))
	if err != nil {
		return Account{}, User{}, err
	}
	u, err := p.adminFor(ctx, a.ID)
	return a, u, err
}

func (p *Postgres) Account(ctx context.Context, id string) (Account, error) {
	return scanAccount(p.pool.QueryRow(ctx, accountSelect+` WHERE id=$1`, id))
}

func (p *Postgres) adminFor(ctx context.Context, accountID string) (User, error) {
	rows, err := p.pool.Query(ctx, userSelect+` WHERE account_id=$1 AND kind='admin' ORDER BY created_at LIMIT 1`, accountID)
	if err != nil {
		return User{}, err
	}
	defer rows.Close()
	if !rows.Next() {
		return User{}, ErrNotFound
	}
	return scanUser(rows)
}

// COALESCE keeps NULLs from older Python rows scannable into Go strings.
const accountSelect = `SELECT id, username, coalesce(password_hash,''), created_at FROM accounts`

const userSelect = `SELECT id, account_id, kind, coalesce(track,''), coalesce(email,''), coalesce(password_hash,''), coalesce(display_name,''), coalesce(metadata_json,'{}'), coalesce(created_by,''), coalesce(disabled_at,''), created_at FROM users`

func scanAccount(row pgx.Row) (Account, error) {
	var a Account
	err := row.Scan(&a.ID, &a.Username, &a.PasswordHash, &a.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return Account{}, ErrNotFound
	}
	return a, err
}

func scanUser(row pgx.Row) (User, error) {
	var u User
	var meta string
	err := row.Scan(&u.ID, &u.AccountID, &u.Kind, &u.Track, &u.Email, &u.PasswordHash, &u.DisplayName, &meta, &u.CreatedBy, &u.DisabledAt, &u.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return User{}, ErrNotFound
	}
	u.Metadata = []byte(meta)
	return u, err
}

func (p *Postgres) CreateUser(ctx context.Context, u User) error {
	_, err := p.pool.Exec(ctx, `
		INSERT INTO users (id, account_id, kind, track, email, password_hash, display_name, metadata_json, created_by, disabled_at, created_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`,
		u.ID, u.AccountID, u.Kind, u.Track, u.Email, u.PasswordHash, u.DisplayName, rawOr(u.Metadata, "{}"), u.CreatedBy, u.DisabledAt, u.CreatedAt)
	if isUnique(err) {
		return ErrConflict
	}
	return err
}

func (p *Postgres) User(ctx context.Context, id string) (User, error) {
	return scanUser(p.pool.QueryRow(ctx, userSelect+` WHERE id=$1`, id))
}

func (p *Postgres) UserByEmail(ctx context.Context, email string) (User, error) {
	email = strings.TrimSpace(email)
	if email == "" {
		return User{}, ErrNotFound
	}
	return scanUser(p.pool.QueryRow(ctx, userSelect+` WHERE lower(email)=lower($1) AND email <> ''`, email))
}

func (p *Postgres) FirstAdmin(ctx context.Context) (User, error) {
	row := p.pool.QueryRow(ctx, userSelect+` WHERE kind='admin' AND coalesce(disabled_at,'')='' ORDER BY created_at LIMIT 1`)
	return scanUser(row)
}

func (p *Postgres) ListUsers(ctx context.Context, accountID, kind, track string) ([]User, error) {
	q := userSelect + ` WHERE account_id=$1`
	args := []any{accountID}
	if kind != "" {
		args = append(args, kind)
		q += fmt.Sprintf(" AND kind=$%d", len(args))
	}
	if track != "" {
		args = append(args, track)
		q += fmt.Sprintf(" AND track=$%d", len(args))
	}
	rows, err := p.pool.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []User
	for rows.Next() {
		u, err := scanUser(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, u)
	}
	return out, rows.Err()
}

func (p *Postgres) SaveUser(ctx context.Context, u User) error {
	tag, err := p.pool.Exec(ctx, `
		UPDATE users SET kind=$2, track=$3, email=$4, password_hash=$5, display_name=$6, metadata_json=$7, disabled_at=$8
		WHERE id=$1`, u.ID, u.Kind, u.Track, u.Email, u.PasswordHash, u.DisplayName, rawOr(u.Metadata, "{}"), u.DisabledAt)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

func (p *Postgres) CreateSession(ctx context.Context, s Session) error {
	_, err := p.pool.Exec(ctx, `INSERT INTO sessions (id, account_id, user_id, token_hash, csrf_hash, expires_at, last_seen) VALUES ($1,$2,$3,$4,$5,$6,$7)`,
		s.ID, s.AccountID, s.UserID, s.TokenHash, s.CSRFHash, s.ExpiresAt, s.LastSeen)
	return err
}

func (p *Postgres) SessionByHash(ctx context.Context, hash string) (Session, error) {
	var s Session
	err := p.pool.QueryRow(ctx, `SELECT id, account_id, user_id, token_hash, csrf_hash, expires_at, last_seen FROM sessions WHERE token_hash=$1`, hash).
		Scan(&s.ID, &s.AccountID, &s.UserID, &s.TokenHash, &s.CSRFHash, &s.ExpiresAt, &s.LastSeen)
	if errors.Is(err, pgx.ErrNoRows) {
		return Session{}, ErrNotFound
	}
	return s, err
}

func (p *Postgres) DeleteSession(ctx context.Context, id string) error {
	_, err := p.pool.Exec(ctx, `DELETE FROM sessions WHERE id=$1`, id)
	return err
}

func (p *Postgres) CreateAPIKey(ctx context.Context, k APIKey) error {
	_, err := p.pool.Exec(ctx, `INSERT INTO api_keys (id, account_id, user_id, prefix, key_hash, created_at, revoked_at) VALUES ($1,$2,$3,$4,$5,$6,$7)`,
		k.ID, k.AccountID, k.UserID, k.Prefix, k.KeyHash, k.CreatedAt, k.RevokedAt)
	return err
}

func (p *Postgres) APIKeyByHash(ctx context.Context, hash string) (APIKey, error) {
	var k APIKey
	err := p.pool.QueryRow(ctx, `SELECT id, account_id, user_id, prefix, key_hash, created_at, revoked_at FROM api_keys WHERE key_hash=$1`, hash).
		Scan(&k.ID, &k.AccountID, &k.UserID, &k.Prefix, &k.KeyHash, &k.CreatedAt, &k.RevokedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return APIKey{}, ErrNotFound
	}
	return k, err
}

func (p *Postgres) RevokeUserKeys(ctx context.Context, userID string, at string) error {
	_, err := p.pool.Exec(ctx, `UPDATE api_keys SET revoked_at=$2 WHERE user_id=$1 AND revoked_at=''`, userID, at)
	return err
}

func (p *Postgres) CreateInvite(ctx context.Context, inv Invite) error {
	_, err := p.pool.Exec(ctx, `INSERT INTO invites (id, account_id, track, mode, secret_hash, max_redemptions, redemptions, expires_at, revoked_at, created_by, allow_multiple_owners, created_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)`,
		inv.ID, inv.AccountID, inv.Track, inv.Mode, inv.SecretHash, inv.MaxRedemptions, inv.Redemptions, inv.ExpiresAt, inv.RevokedAt, inv.CreatedBy, inv.AllowMultipleOwners, inv.CreatedAt)
	return err
}

func scanInvite(row pgx.Row) (Invite, error) {
	var inv Invite
	err := row.Scan(&inv.ID, &inv.AccountID, &inv.Track, &inv.Mode, &inv.SecretHash, &inv.MaxRedemptions, &inv.Redemptions, &inv.ExpiresAt, &inv.RevokedAt, &inv.CreatedBy, &inv.AllowMultipleOwners, &inv.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return Invite{}, ErrNotFound
	}
	return inv, err
}

const inviteSelect = `SELECT id, account_id, track, mode, secret_hash, max_redemptions, redemptions, expires_at, revoked_at, created_by, allow_multiple_owners, created_at FROM invites`

func (p *Postgres) Invite(ctx context.Context, id string) (Invite, error) {
	return scanInvite(p.pool.QueryRow(ctx, inviteSelect+` WHERE id=$1`, id))
}

func (p *Postgres) ListInvites(ctx context.Context, accountID string) ([]Invite, error) {
	rows, err := p.pool.Query(ctx, inviteSelect+` WHERE account_id=$1`, accountID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Invite
	for rows.Next() {
		inv, err := scanInvite(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, inv)
	}
	return out, rows.Err()
}

func (p *Postgres) SaveInvite(ctx context.Context, inv Invite) error {
	tag, err := p.pool.Exec(ctx, `UPDATE invites SET redemptions=$2, revoked_at=$3 WHERE id=$1`, inv.ID, inv.Redemptions, inv.RevokedAt)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

func (p *Postgres) SaveJob(ctx context.Context, j Job) error {
	_, err := p.pool.Exec(ctx, `
		INSERT INTO jobs (
			account_id, id, company, title, location, remote, url, apply_url, apply_kind, ats, req_id,
			sources_json, status, score, owners_json, apply_packet_json, outreach_packet_json, research_json, proof_json,
			notes, description, expectations, pay, posted_at, rejection_json, conflicts_json, stopped, stop_reason,
			created_at, updated_at, created_by_role
		) VALUES (
			$1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31
		)
		ON CONFLICT (account_id, id) DO UPDATE SET
			company=EXCLUDED.company, title=EXCLUDED.title, location=EXCLUDED.location, remote=EXCLUDED.remote,
			url=EXCLUDED.url, apply_url=EXCLUDED.apply_url, apply_kind=EXCLUDED.apply_kind, ats=EXCLUDED.ats, req_id=EXCLUDED.req_id,
			sources_json=EXCLUDED.sources_json, status=EXCLUDED.status, score=EXCLUDED.score, owners_json=EXCLUDED.owners_json,
			apply_packet_json=EXCLUDED.apply_packet_json, outreach_packet_json=EXCLUDED.outreach_packet_json,
			research_json=EXCLUDED.research_json, proof_json=EXCLUDED.proof_json, notes=EXCLUDED.notes,
			description=EXCLUDED.description, expectations=EXCLUDED.expectations, pay=EXCLUDED.pay, posted_at=EXCLUDED.posted_at,
			rejection_json=EXCLUDED.rejection_json, conflicts_json=EXCLUDED.conflicts_json, stopped=EXCLUDED.stopped,
			stop_reason=EXCLUDED.stop_reason, updated_at=EXCLUDED.updated_at`,
		j.AccountID, j.ID, j.Company, j.Title, j.Location, j.Remote, j.URL, j.ApplyURL, j.ApplyKind, j.ATS, j.ReqID,
		rawOr(j.Sources, "[]"), j.Status, j.Score, rawOr(j.Owners, "{}"), rawOr(j.ApplyPacket, "{}"), rawOr(j.OutreachPacket, "{}"),
		rawOr(j.Research, "{}"), rawOr(j.Proof, "{}"), j.Notes, j.Description, j.Expectations, j.Pay, j.PostedAt,
		rawOr(j.Rejection, "{}"), rawOr(j.Conflicts, "[]"), j.Stopped, j.StopReason, j.CreatedAt, j.UpdatedAt, j.CreatedByRole)
	return err
}

const jobSelect = `SELECT account_id, id, company, title, location, remote, url, apply_url, apply_kind, ats, req_id,
	sources_json, status, score, owners_json, apply_packet_json, outreach_packet_json, research_json, proof_json,
	notes, description, expectations, pay, posted_at, rejection_json, conflicts_json, stopped, stop_reason,
	created_at, updated_at, created_by_role FROM jobs`

func scanJob(row pgx.Row) (Job, error) {
	var j Job
	var sources, owners, apply, outreach, research, proof, rejection, conflicts string
	err := row.Scan(
		&j.AccountID, &j.ID, &j.Company, &j.Title, &j.Location, &j.Remote, &j.URL, &j.ApplyURL, &j.ApplyKind, &j.ATS, &j.ReqID,
		&sources, &j.Status, &j.Score, &owners, &apply, &outreach, &research, &proof,
		&j.Notes, &j.Description, &j.Expectations, &j.Pay, &j.PostedAt, &rejection, &conflicts, &j.Stopped, &j.StopReason,
		&j.CreatedAt, &j.UpdatedAt, &j.CreatedByRole,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return Job{}, ErrNotFound
	}
	if err != nil {
		return Job{}, err
	}
	j.Sources, j.Owners, j.ApplyPacket, j.OutreachPacket = []byte(sources), []byte(owners), []byte(apply), []byte(outreach)
	j.Research, j.Proof, j.Rejection, j.Conflicts = []byte(research), []byte(proof), []byte(rejection), []byte(conflicts)
	return j, nil
}

func (p *Postgres) Job(ctx context.Context, accountID, id string) (Job, error) {
	return scanJob(p.pool.QueryRow(ctx, jobSelect+` WHERE account_id=$1 AND id=$2`, accountID, id))
}

func (p *Postgres) ListJobs(ctx context.Context, f JobFilter) ([]Job, int, int, error) {
	where := []string{"account_id=$1"}
	args := []any{f.AccountID}
	add := func(cond string, val any) {
		args = append(args, val)
		where = append(where, fmt.Sprintf(cond, len(args)))
	}
	if f.Status != "" {
		add("status=$%d", f.Status)
	}
	if f.Stopped != nil {
		add("stopped=$%d", *f.Stopped)
	}
	if f.ApplyKind != "" {
		add("apply_kind=$%d", f.ApplyKind)
	}
	if f.Location != "" {
		add("location ILIKE $%d", "%"+f.Location+"%")
	}
	if f.Company != "" {
		add("company ILIKE $%d", "%"+f.Company+"%")
	}
	if f.Remote != "" {
		add("lower(remote)=lower($%d)", f.Remote)
	}
	if f.HasPay != nil {
		if *f.HasPay {
			where = append(where, "pay <> ''")
		} else {
			where = append(where, "pay = ''")
		}
	}
	if f.ScoreMin != nil {
		add("score >= $%d", *f.ScoreMin)
	}
	if f.ScoreMax != nil {
		add("score <= $%d", *f.ScoreMax)
	}
	if f.Q != "" {
		args = append(args, "%"+f.Q+"%")
		n := len(args)
		where = append(where, fmt.Sprintf("(company ILIKE $%d OR title ILIKE $%d OR location ILIKE $%d OR notes ILIKE $%d)", n, n, n, n))
	}
	if len(f.Lane) > 0 {
		args = append(args, f.Lane)
		where = append(where, fmt.Sprintf("status = ANY($%d)", len(args)))
	}
	clause := strings.Join(where, " AND ")
	var matched, total int
	if err := p.pool.QueryRow(ctx, `SELECT count(*) FROM jobs WHERE `+clause, args...).Scan(&matched); err != nil {
		return nil, 0, 0, err
	}
	if err := p.pool.QueryRow(ctx, `SELECT count(*) FROM jobs WHERE account_id=$1`, f.AccountID).Scan(&total); err != nil {
		return nil, 0, 0, err
	}
	q := jobSelect + ` WHERE ` + clause + ` ORDER BY updated_at DESC`
	qArgs := append([]any{}, args...)
	if f.Limit > 0 {
		qArgs = append(qArgs, f.Limit)
		q += fmt.Sprintf(" LIMIT $%d", len(qArgs))
	}
	if f.Offset > 0 {
		qArgs = append(qArgs, f.Offset)
		q += fmt.Sprintf(" OFFSET $%d", len(qArgs))
	}
	rows, err := p.pool.Query(ctx, q, qArgs...)
	if err != nil {
		return nil, 0, 0, err
	}
	defer rows.Close()
	var out []Job
	for rows.Next() {
		j, err := scanJob(rows)
		if err != nil {
			return nil, 0, 0, err
		}
		out = append(out, j)
	}
	return out, matched, total, rows.Err()
}

func (p *Postgres) DeleteJob(ctx context.Context, accountID, id string) error {
	tag, err := p.pool.Exec(ctx, `DELETE FROM jobs WHERE account_id=$1 AND id=$2`, accountID, id)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

func (p *Postgres) FindDuplicate(ctx context.Context, accountID, applyURL, company, title, location string) (Job, bool, error) {
	if strings.TrimSpace(applyURL) != "" {
		j, err := scanJob(p.pool.QueryRow(ctx, jobSelect+` WHERE account_id=$1 AND apply_url=$2 LIMIT 1`, accountID, applyURL))
		if err == nil {
			return j, true, nil
		}
		if !errors.Is(err, ErrNotFound) {
			return Job{}, false, err
		}
	}
	j, err := scanJob(p.pool.QueryRow(ctx, jobSelect+` WHERE account_id=$1 AND lower(company)=lower($2) AND lower(title)=lower($3) AND lower(location)=lower($4) LIMIT 1`,
		accountID, company, title, location))
	if errors.Is(err, ErrNotFound) {
		return Job{}, false, nil
	}
	if err != nil {
		return Job{}, false, err
	}
	return j, true, nil
}

func (p *Postgres) CountByStatus(ctx context.Context, accountID string) (map[string]int, error) {
	rows, err := p.pool.Query(ctx, `SELECT status, count(*) FROM jobs WHERE account_id=$1 GROUP BY status`, accountID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[string]int{}
	for rows.Next() {
		var status string
		var n int
		if err := rows.Scan(&status, &n); err != nil {
			return nil, err
		}
		out[status] = n
	}
	return out, rows.Err()
}

func (p *Postgres) AddEvent(ctx context.Context, e Event) (Event, error) {
	err := p.pool.QueryRow(ctx, `
		INSERT INTO events (account_id, ts, job_id, actor_role, actor, action, from_status, to_status, note, fields_json)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id`,
		e.AccountID, e.TS, e.JobID, e.ActorRole, e.Actor, e.Action, e.FromStatus, e.ToStatus, e.Note, rawOr(e.Fields, "{}")).Scan(&e.ID)
	return e, err
}

func (p *Postgres) ListEvents(ctx context.Context, accountID, jobID string, limit int) ([]Event, error) {
	q := `SELECT id, account_id, ts, job_id, actor_role, actor, action, from_status, to_status, note, fields_json FROM events WHERE account_id=$1`
	args := []any{accountID}
	if jobID != "" {
		args = append(args, jobID)
		q += fmt.Sprintf(" AND job_id=$%d", len(args))
	}
	q += " ORDER BY id DESC"
	if limit <= 0 {
		limit = 100
	}
	args = append(args, limit)
	q += fmt.Sprintf(" LIMIT $%d", len(args))
	rows, err := p.pool.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Event
	for rows.Next() {
		var e Event
		var fields string
		if err := rows.Scan(&e.ID, &e.AccountID, &e.TS, &e.JobID, &e.ActorRole, &e.Actor, &e.Action, &e.FromStatus, &e.ToStatus, &e.Note, &fields); err != nil {
			return nil, err
		}
		e.Fields = []byte(fields)
		out = append(out, e)
	}
	return out, rows.Err()
}

func (p *Postgres) SaveQueue(ctx context.Context, q QueueItem) error {
	_, err := p.pool.Exec(ctx, `
		INSERT INTO queue_items (id, account_id, kind, track, job_id, payload_json, status, claimed_by, lease_until, attempts, dedupe_key, created_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
		ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status, claimed_by=EXCLUDED.claimed_by, lease_until=EXCLUDED.lease_until, attempts=EXCLUDED.attempts, payload_json=EXCLUDED.payload_json`,
		q.ID, q.AccountID, q.Kind, q.Track, q.JobID, rawOr(q.Payload, "{}"), q.Status, q.ClaimedBy, q.LeaseUntil, q.Attempts, q.DedupeKey, q.CreatedAt)
	return err
}

const queueSelect = `SELECT id, account_id, kind, track, job_id, payload_json, status, claimed_by, lease_until, attempts, dedupe_key, created_at FROM queue_items`

func scanQueue(row pgx.Row) (QueueItem, error) {
	var q QueueItem
	var payload string
	err := row.Scan(&q.ID, &q.AccountID, &q.Kind, &q.Track, &q.JobID, &payload, &q.Status, &q.ClaimedBy, &q.LeaseUntil, &q.Attempts, &q.DedupeKey, &q.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return QueueItem{}, ErrNotFound
	}
	q.Payload = []byte(payload)
	return q, err
}

func (p *Postgres) QueueByID(ctx context.Context, accountID, id string) (QueueItem, error) {
	return scanQueue(p.pool.QueryRow(ctx, queueSelect+` WHERE account_id=$1 AND id=$2`, accountID, id))
}

func (p *Postgres) QueueByDedupe(ctx context.Context, accountID, key string) (QueueItem, bool, error) {
	q, err := scanQueue(p.pool.QueryRow(ctx, queueSelect+` WHERE account_id=$1 AND dedupe_key=$2`, accountID, key))
	if errors.Is(err, ErrNotFound) {
		return QueueItem{}, false, nil
	}
	if err != nil {
		return QueueItem{}, false, err
	}
	return q, true, nil
}

func (p *Postgres) ClaimQueue(ctx context.Context, accountID, who string, kinds []string, now, leaseUntil string) (QueueItem, bool, error) {
	row := p.pool.QueryRow(ctx, `
		WITH picked AS (
			SELECT id FROM queue_items
			 WHERE account_id=$1
			   AND kind = ANY($2)
			   AND status IN ('open','claimed')
			   AND (status='open' OR lease_until='' OR lease_until < $3)
			 ORDER BY id
			 LIMIT 1
			 FOR UPDATE SKIP LOCKED
		)
		UPDATE queue_items q
		   SET status='claimed', claimed_by=$4, lease_until=$5
		  FROM picked
		 WHERE q.id = picked.id
		RETURNING q.id, q.account_id, q.kind, q.track, q.job_id, q.payload_json, q.status, q.claimed_by, q.lease_until, q.attempts, q.dedupe_key, q.created_at`,
		accountID, kinds, now, who, leaseUntil)
	q, err := scanQueue(row)
	if errors.Is(err, ErrNotFound) {
		return QueueItem{}, false, nil
	}
	if err != nil {
		return QueueItem{}, false, err
	}
	return q, true, nil
}

func (p *Postgres) ListQueue(ctx context.Context, accountID, claimedBy, status string) ([]QueueItem, error) {
	q := queueSelect + ` WHERE account_id=$1`
	args := []any{accountID}
	if claimedBy != "" {
		args = append(args, claimedBy)
		q += fmt.Sprintf(" AND claimed_by=$%d", len(args))
	}
	if status != "" {
		args = append(args, status)
		q += fmt.Sprintf(" AND status=$%d", len(args))
	}
	rows, err := p.pool.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []QueueItem
	for rows.Next() {
		item, err := scanQueue(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (p *Postgres) SavePerson(ctx context.Context, person Person) error {
	_, err := p.pool.Exec(ctx, `
		INSERT INTO people (account_id, id, name, title, company, job_id, linkedin_url, email, email_confidence, do_not_contact, touches_json, notes, created_at, updated_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
		ON CONFLICT (account_id, id) DO UPDATE SET
			name=EXCLUDED.name, title=EXCLUDED.title, company=EXCLUDED.company, job_id=EXCLUDED.job_id,
			linkedin_url=EXCLUDED.linkedin_url, email=EXCLUDED.email, email_confidence=EXCLUDED.email_confidence,
			do_not_contact=EXCLUDED.do_not_contact, touches_json=EXCLUDED.touches_json, notes=EXCLUDED.notes, updated_at=EXCLUDED.updated_at`,
		person.AccountID, person.ID, person.Name, person.Title, person.Company, person.JobID, person.LinkedinURL, person.Email,
		person.EmailConfidence, person.DoNotContact, rawOr(person.Touches, "[]"), person.Notes, person.CreatedAt, person.UpdatedAt)
	return err
}

func (p *Postgres) Person(ctx context.Context, accountID, id string) (Person, error) {
	return scanPerson(p.pool.QueryRow(ctx, personSelect+` WHERE account_id=$1 AND id=$2`, accountID, id))
}

const personSelect = `SELECT account_id, id, name, title, company, job_id, linkedin_url, email, email_confidence, do_not_contact, touches_json, notes, created_at, updated_at FROM people`

func scanPerson(row pgx.Row) (Person, error) {
	var person Person
	var touches string
	err := row.Scan(&person.AccountID, &person.ID, &person.Name, &person.Title, &person.Company, &person.JobID, &person.LinkedinURL, &person.Email, &person.EmailConfidence, &person.DoNotContact, &touches, &person.Notes, &person.CreatedAt, &person.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return Person{}, ErrNotFound
	}
	person.Touches = []byte(touches)
	return person, err
}

func (p *Postgres) ListPeople(ctx context.Context, accountID, company, jobID string) ([]Person, error) {
	q := personSelect + ` WHERE account_id=$1`
	args := []any{accountID}
	if company != "" {
		args = append(args, company)
		q += fmt.Sprintf(" AND lower(company)=lower($%d)", len(args))
	}
	if jobID != "" {
		args = append(args, jobID)
		q += fmt.Sprintf(" AND job_id=$%d", len(args))
	}
	rows, err := p.pool.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Person
	for rows.Next() {
		person, err := scanPerson(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, person)
	}
	return out, rows.Err()
}

func (p *Postgres) SaveMemory(ctx context.Context, item MemoryItem) error {
	tags := item.Tags
	if len(tags) == 0 {
		tags = []byte("[]")
	}
	_, err := p.pool.Exec(ctx, `
		INSERT INTO memory_items (id, account_id, pod, kind, title, body, job_id, company, content_hash, importance, expires_at, pinned, tags_json, solidify_status, created_by, created_at, updated_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
		ON CONFLICT (id) DO UPDATE SET
			pod=EXCLUDED.pod, kind=EXCLUDED.kind, title=EXCLUDED.title, body=EXCLUDED.body, job_id=EXCLUDED.job_id,
			company=EXCLUDED.company, content_hash=EXCLUDED.content_hash, importance=EXCLUDED.importance,
			expires_at=EXCLUDED.expires_at, pinned=EXCLUDED.pinned, tags_json=EXCLUDED.tags_json,
			solidify_status=EXCLUDED.solidify_status, updated_at=EXCLUDED.updated_at`,
		item.ID, item.AccountID, item.Pod, item.Kind, item.Title, item.Body, item.JobID, item.Company, item.ContentHash, item.Importance, item.ExpiresAt, item.Pinned, string(tags), item.SolidifyStatus, item.CreatedBy, item.CreatedAt, item.UpdatedAt)
	return err
}

func scanMemory(row pgx.Row) (MemoryItem, error) {
	var item MemoryItem
	var tags string
	err := row.Scan(&item.ID, &item.AccountID, &item.Pod, &item.Kind, &item.Title, &item.Body, &item.JobID, &item.Company, &item.ContentHash, &item.Importance, &item.ExpiresAt, &item.Pinned, &tags, &item.SolidifyStatus, &item.CreatedBy, &item.CreatedAt, &item.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return MemoryItem{}, ErrNotFound
	}
	if tags != "" {
		item.Tags = []byte(tags)
	}
	return item, err
}

const memorySelect = `SELECT id, account_id, pod, kind, title, body, job_id, company, content_hash, importance, expires_at, pinned, tags_json, solidify_status, created_by, created_at, updated_at FROM memory_items`

func (p *Postgres) Memory(ctx context.Context, accountID, id string) (MemoryItem, error) {
	return scanMemory(p.pool.QueryRow(ctx, memorySelect+` WHERE account_id=$1 AND id=$2`, accountID, id))
}

func (p *Postgres) ListMemory(ctx context.Context, accountID, pod string) ([]MemoryItem, error) {
	q := memorySelect + ` WHERE account_id=$1`
	args := []any{accountID}
	if pod != "" {
		args = append(args, pod, pod+":%")
		q += fmt.Sprintf(" AND (pod=$%d OR pod LIKE $%d)", len(args)-1, len(args))
	}
	rows, err := p.pool.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []MemoryItem
	for rows.Next() {
		item, err := scanMemory(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (p *Postgres) DeleteMemory(ctx context.Context, accountID, id string) error {
	tag, err := p.pool.Exec(ctx, `DELETE FROM memory_items WHERE account_id=$1 AND id=$2`, accountID, id)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

func (p *Postgres) SaveMessage(ctx context.Context, msg Message) error {
	_, err := p.pool.Exec(ctx, `
		INSERT INTO messages (id, account_id, from_user_id, to_user_id, to_track, job_id, type, body, created_at, read_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
		ON CONFLICT (id) DO UPDATE SET read_at=EXCLUDED.read_at`,
		msg.ID, msg.AccountID, msg.FromUserID, msg.ToUserID, msg.ToTrack, msg.JobID, msg.Type, msg.Body, msg.CreatedAt, msg.ReadAt)
	return err
}

func scanMessage(row pgx.Row) (Message, error) {
	var msg Message
	err := row.Scan(&msg.ID, &msg.AccountID, &msg.FromUserID, &msg.ToUserID, &msg.ToTrack, &msg.JobID, &msg.Type, &msg.Body, &msg.CreatedAt, &msg.ReadAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return Message{}, ErrNotFound
	}
	return msg, err
}

func (p *Postgres) ListMessages(ctx context.Context, accountID string, unreadOnly bool) ([]Message, error) {
	q := `SELECT id, account_id, from_user_id, to_user_id, to_track, job_id, type, body, created_at, read_at FROM messages WHERE account_id=$1`
	if unreadOnly {
		q += ` AND read_at=''`
	}
	q += ` ORDER BY created_at DESC`
	rows, err := p.pool.Query(ctx, q, accountID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Message
	for rows.Next() {
		msg, err := scanMessage(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, msg)
	}
	return out, rows.Err()
}

func (p *Postgres) Message(ctx context.Context, accountID, id string) (Message, error) {
	return scanMessage(p.pool.QueryRow(ctx, `SELECT id, account_id, from_user_id, to_user_id, to_track, job_id, type, body, created_at, read_at FROM messages WHERE account_id=$1 AND id=$2`, accountID, id))
}

func (p *Postgres) SaveSkill(ctx context.Context, s Skill) error {
	_, err := p.pool.Exec(ctx, `
		INSERT INTO skills (id, account_id, slug, name, kind, role, tags_json, scope, owner_user_id, status, platform, body, origin, version, created_at, updated_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
		ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, body=EXCLUDED.body, status=EXCLUDED.status, tags_json=EXCLUDED.tags_json, version=EXCLUDED.version, updated_at=EXCLUDED.updated_at`,
		s.ID, s.AccountID, s.Slug, s.Name, s.Kind, s.Role, rawOr(s.Tags, "[]"), s.Scope, s.OwnerID, s.Status, s.Platform, s.Body, s.Origin, s.Version, s.CreatedAt, s.UpdatedAt)
	return err
}

func scanSkill(row pgx.Row) (Skill, error) {
	var s Skill
	var tags string
	err := row.Scan(&s.ID, &s.AccountID, &s.Slug, &s.Name, &s.Kind, &s.Role, &tags, &s.Scope, &s.OwnerID, &s.Status, &s.Platform, &s.Body, &s.Origin, &s.Version, &s.CreatedAt, &s.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return Skill{}, ErrNotFound
	}
	s.Tags = []byte(tags)
	return s, err
}

const skillSelect = `SELECT id, account_id, slug, name, kind, role, tags_json, scope, owner_user_id, status, platform, body, origin, version, created_at, updated_at FROM skills`

func (p *Postgres) Skill(ctx context.Context, id string) (Skill, error) {
	return scanSkill(p.pool.QueryRow(ctx, skillSelect+` WHERE id=$1`, id))
}

func (p *Postgres) ListSkills(ctx context.Context, accountID, scope, status, tag string) ([]Skill, error) {
	q := skillSelect + ` WHERE (scope='shared' OR account_id=$1)`
	args := []any{accountID}
	if scope != "" {
		args = append(args, scope)
		q += fmt.Sprintf(" AND scope=$%d", len(args))
	}
	if status != "" {
		args = append(args, status)
		q += fmt.Sprintf(" AND status=$%d", len(args))
	}
	if tag != "" {
		args = append(args, "%\""+tag+"\"%")
		q += fmt.Sprintf(" AND tags_json LIKE $%d", len(args))
	}
	rows, err := p.pool.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Skill
	for rows.Next() {
		s, err := scanSkill(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

func (p *Postgres) SaveMCP(ctx context.Context, item MCP) error {
	_, err := p.pool.Exec(ctx, `
		INSERT INTO mcps (account_id, id, slug, name, kind, status, capability_json, roles_json, platforms_json, source, install, auth, notes, origin, created_at, updated_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
		ON CONFLICT (account_id, id) DO UPDATE SET
			name=EXCLUDED.name, kind=EXCLUDED.kind, status=EXCLUDED.status, capability_json=EXCLUDED.capability_json,
			roles_json=EXCLUDED.roles_json, platforms_json=EXCLUDED.platforms_json, source=EXCLUDED.source,
			install=EXCLUDED.install, auth=EXCLUDED.auth, notes=EXCLUDED.notes, updated_at=EXCLUDED.updated_at`,
		item.AccountID, item.ID, item.Slug, item.Name, item.Kind, item.Status, rawOr(item.Capability, "[]"), rawOr(item.Roles, "[]"),
		rawOr(item.Platforms, "[]"), item.Source, item.Install, item.Auth, item.Notes, item.Origin, item.CreatedAt, item.UpdatedAt)
	return err
}

func scanMCP(row pgx.Row) (MCP, error) {
	var item MCP
	var capability, roles, platforms string
	err := row.Scan(&item.AccountID, &item.ID, &item.Slug, &item.Name, &item.Kind, &item.Status, &capability, &roles, &platforms, &item.Source, &item.Install, &item.Auth, &item.Notes, &item.Origin, &item.CreatedAt, &item.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return MCP{}, ErrNotFound
	}
	item.Capability, item.Roles, item.Platforms = []byte(capability), []byte(roles), []byte(platforms)
	return item, err
}

const mcpSelect = `SELECT account_id, id, slug, name, kind, status, capability_json, roles_json, platforms_json, source, install, auth, notes, origin, created_at, updated_at FROM mcps`

func (p *Postgres) MCP(ctx context.Context, accountID, idOrSlug string) (MCP, error) {
	item, err := scanMCP(p.pool.QueryRow(ctx, mcpSelect+` WHERE (account_id=$1 OR account_id='shared') AND (id=$2 OR slug=$2) LIMIT 1`, accountID, idOrSlug))
	return item, err
}

func (p *Postgres) ListMCPs(ctx context.Context, accountID string) ([]MCP, error) {
	rows, err := p.pool.Query(ctx, mcpSelect+` WHERE account_id=$1 OR account_id='shared'`, accountID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []MCP
	for rows.Next() {
		item, err := scanMCP(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (p *Postgres) SaveRecording(ctx context.Context, r Recording) error {
	_, err := p.pool.Exec(ctx, `
		INSERT INTO skill_recordings (id, account_id, skill_id, submitter_user_id, origin, body, status, proctor_note, created_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
		ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status, proctor_note=EXCLUDED.proctor_note, body=EXCLUDED.body`,
		r.ID, r.AccountID, r.SkillID, r.SubmitterID, r.Origin, r.Body, r.Status, r.Note, r.CreatedAt)
	return err
}

func scanRecording(row pgx.Row) (Recording, error) {
	var r Recording
	err := row.Scan(&r.ID, &r.AccountID, &r.SkillID, &r.SubmitterID, &r.Origin, &r.Body, &r.Status, &r.Note, &r.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return Recording{}, ErrNotFound
	}
	return r, err
}

func (p *Postgres) Recording(ctx context.Context, id string) (Recording, error) {
	return scanRecording(p.pool.QueryRow(ctx, `SELECT id, account_id, skill_id, submitter_user_id, origin, body, status, proctor_note, created_at FROM skill_recordings WHERE id=$1`, id))
}

func (p *Postgres) ListRecordings(ctx context.Context, accountID, status string) ([]Recording, error) {
	q := `SELECT id, account_id, skill_id, submitter_user_id, origin, body, status, proctor_note, created_at FROM skill_recordings WHERE account_id=$1`
	args := []any{accountID}
	if status != "" {
		args = append(args, status)
		q += fmt.Sprintf(" AND status=$%d", len(args))
	}
	rows, err := p.pool.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Recording
	for rows.Next() {
		r, err := scanRecording(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

func (p *Postgres) SavePresence(ctx context.Context, pr Presence) error {
	_, err := p.pool.Exec(ctx, `
		INSERT INTO presence (account_id, user_id, status, task_id, last_heartbeat, user_agent)
		VALUES ($1,$2,$3,$4,$5,$6)
		ON CONFLICT (account_id, user_id) DO UPDATE SET status=EXCLUDED.status, task_id=EXCLUDED.task_id, last_heartbeat=EXCLUDED.last_heartbeat, user_agent=EXCLUDED.user_agent`,
		pr.AccountID, pr.UserID, pr.Status, pr.TaskID, pr.LastBeat, pr.UserAgent)
	return err
}

func (p *Postgres) ListPresence(ctx context.Context, accountID string) ([]Presence, error) {
	rows, err := p.pool.Query(ctx, `SELECT account_id, user_id, status, task_id, last_heartbeat, user_agent FROM presence WHERE account_id=$1`, accountID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Presence
	for rows.Next() {
		var pr Presence
		if err := rows.Scan(&pr.AccountID, &pr.UserID, &pr.Status, &pr.TaskID, &pr.LastBeat, &pr.UserAgent); err != nil {
			return nil, err
		}
		out = append(out, pr)
	}
	return out, rows.Err()
}

func (p *Postgres) AddBurn(ctx context.Context, b Burn) (Burn, error) {
	err := p.pool.QueryRow(ctx, `
		INSERT INTO token_burn (account_id, ts, tool_name, skill, lane, prompt_tokens, completion_tokens, total_tokens, cost_usd, job_id, actor_role, actor)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) RETURNING id`,
		b.AccountID, b.TS, b.ToolName, b.Skill, b.Lane, b.PromptTokens, b.CompletionTokens, b.TotalTokens, b.CostUSD, b.JobID, b.ActorRole, b.Actor).Scan(&b.ID)
	return b, err
}

func (p *Postgres) ListBurns(ctx context.Context, accountID string, limit int) ([]Burn, error) {
	if limit <= 0 {
		limit = 100
	}
	rows, err := p.pool.Query(ctx, `SELECT id, account_id, ts, tool_name, skill, lane, prompt_tokens, completion_tokens, total_tokens, cost_usd, job_id, actor_role, actor FROM token_burn WHERE account_id=$1 ORDER BY id DESC LIMIT $2`, accountID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Burn
	for rows.Next() {
		var b Burn
		if err := rows.Scan(&b.ID, &b.AccountID, &b.TS, &b.ToolName, &b.Skill, &b.Lane, &b.PromptTokens, &b.CompletionTokens, &b.TotalTokens, &b.CostUSD, &b.JobID, &b.ActorRole, &b.Actor); err != nil {
			return nil, err
		}
		out = append(out, b)
	}
	return out, rows.Err()
}

func (p *Postgres) SavePeer(ctx context.Context, peer Peer) error {
	_, err := p.pool.Exec(ctx, `INSERT INTO a2a_peers (id, account_id, name, url, created_at) VALUES ($1,$2,$3,$4,$5)`,
		peer.ID, peer.AccountID, peer.Name, peer.URL, peer.CreatedAt)
	return err
}

func (p *Postgres) ListPeers(ctx context.Context, accountID string) ([]Peer, error) {
	rows, err := p.pool.Query(ctx, `SELECT id, account_id, name, url, created_at FROM a2a_peers WHERE account_id=$1`, accountID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Peer
	for rows.Next() {
		var peer Peer
		if err := rows.Scan(&peer.ID, &peer.AccountID, &peer.Name, &peer.URL, &peer.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, peer)
	}
	return out, rows.Err()
}

func (p *Postgres) SaveTask(ctx context.Context, t Task) error {
	_, err := p.pool.Exec(ctx, `
		INSERT INTO a2a_tasks (id, account_id, track, state, payload_json, created_at) VALUES ($1,$2,$3,$4,$5,$6)
		ON CONFLICT (id) DO UPDATE SET state=EXCLUDED.state, track=EXCLUDED.track, payload_json=EXCLUDED.payload_json`,
		t.ID, t.AccountID, t.Track, t.State, rawOr(t.Payload, "{}"), t.CreatedAt)
	return err
}

func (p *Postgres) Task(ctx context.Context, accountID, id string) (Task, error) {
	var t Task
	var payload string
	err := p.pool.QueryRow(ctx, `SELECT id, account_id, track, state, payload_json, created_at FROM a2a_tasks WHERE account_id=$1 AND id=$2`, accountID, id).
		Scan(&t.ID, &t.AccountID, &t.Track, &t.State, &payload, &t.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return Task{}, ErrNotFound
	}
	t.Payload = []byte(payload)
	return t, err
}

func (p *Postgres) ListTasks(ctx context.Context, accountID string, limit int) ([]Task, error) {
	if limit <= 0 {
		limit = 50
	}
	rows, err := p.pool.Query(ctx, `SELECT id, account_id, track, state, payload_json, created_at FROM a2a_tasks WHERE account_id=$1 ORDER BY created_at DESC LIMIT $2`, accountID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Task
	for rows.Next() {
		var t Task
		var payload string
		if err := rows.Scan(&t.ID, &t.AccountID, &t.Track, &t.State, &payload, &t.CreatedAt); err != nil {
			return nil, err
		}
		t.Payload = []byte(payload)
		out = append(out, t)
	}
	return out, rows.Err()
}

func (p *Postgres) PutKV(ctx context.Context, key, value, at string) error {
	_, err := p.pool.Exec(ctx, `INSERT INTO hub_kv (key, value, updated_at) VALUES ($1,$2,$3) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at`, key, value, at)
	return err
}

func (p *Postgres) GetKV(ctx context.Context, key string) (string, error) {
	var value string
	err := p.pool.QueryRow(ctx, `SELECT value FROM hub_kv WHERE key=$1`, key).Scan(&value)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", ErrNotFound
	}
	return value, err
}
