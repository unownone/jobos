-- Indexes and constraint fixes after the baseline.
--
-- The indexes below are emitted because those columns exist on the baseline
-- tables: sessions (token_hash, account_id, last_seen), jobs (account_id,
-- status, updated_at), queue_items (account_id, status, kind, id), events
-- (account_id, actor, action, id, ts), presence (account_id, last_heartbeat),
-- messages (account_id, to_user_id, to_track, created_at), memory_items
-- (account_id, pod, pinned, importance, updated_at), token_burn (account_id,
-- id), a2a_peers (account_id, card_url), invites (redemptions, max_redemptions).
--
-- This file does not recreate events.id or token_burn.id. Live Postgres
-- identity columns stay as they are. Fresh installs already use TEXT ids.

CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_account_seen ON sessions(account_id, last_seen);
CREATE INDEX IF NOT EXISTS idx_jobs_status_updated ON jobs(account_id, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_queue_claim ON queue_items(account_id, status, kind, id);
CREATE INDEX IF NOT EXISTS idx_events_account_actor ON events(account_id, actor, id);
CREATE INDEX IF NOT EXISTS idx_events_account_action ON events(account_id, action, id);
CREATE INDEX IF NOT EXISTS idx_events_account_ts ON events(account_id, ts);
CREATE INDEX IF NOT EXISTS idx_presence_account_hb ON presence(account_id, last_heartbeat);
CREATE INDEX IF NOT EXISTS idx_messages_account_to_user ON messages(account_id, to_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_account_to_track ON messages(account_id, to_track, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_recall ON memory_items(account_id, pod, pinned, importance, updated_at);
CREATE INDEX IF NOT EXISTS idx_burn_account_id ON token_burn(account_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_a2a_peers_account_card ON a2a_peers(account_id, card_url);

-- SQLite cannot ADD a CHECK onto an existing table. Rebuild invites when
-- redemptions and max_redemptions are already present (they are, on the baseline).
CREATE TABLE invites__redemptions_chk (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    track TEXT NOT NULL,
    mode TEXT NOT NULL,
    secret_hash TEXT NOT NULL,
    max_redemptions INTEGER NOT NULL,
    redemptions INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_by TEXT,
    allow_multiple_owners INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    CONSTRAINT invites_redemptions_lte_max CHECK (redemptions <= max_redemptions)
);

INSERT INTO invites__redemptions_chk (
    id, account_id, track, mode, secret_hash, max_redemptions, redemptions,
    expires_at, revoked_at, created_by, allow_multiple_owners, created_at
)
SELECT
    id, account_id, track, mode, secret_hash, max_redemptions, redemptions,
    expires_at, revoked_at, created_by, allow_multiple_owners, created_at
FROM invites;

DROP TABLE invites;
ALTER TABLE invites__redemptions_chk RENAME TO invites;

CREATE INDEX IF NOT EXISTS idx_invites_track ON invites(account_id, track);

CREATE TABLE IF NOT EXISTS outbox (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    body_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    dispatched_at TEXT
);

CREATE TABLE IF NOT EXISTS processed_messages (
    id TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL
);
