-- Fresh-install baseline for Job Hub.
--
-- Portable types: TEXT ids, INTEGER 0/1 flags. No identity columns.
-- events.id and token_burn.id are TEXT primary keys in this file.
-- Existing Postgres databases already have those two columns as bigint
-- identity. CREATE TABLE IF NOT EXISTS leaves those live columns in place.
-- This migration baselines them. It does not recreate or alter them.
--
-- Blob payload: hub_blobs.content is BYTEA here. The sqlite copy of this
-- file uses BLOB for that column only.

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    tracks_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS jobs (
    account_id TEXT NOT NULL,
    id TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    remote TEXT,
    url TEXT,
    apply_url TEXT,
    apply_kind TEXT,
    ats TEXT,
    req_id TEXT,
    sources_json TEXT,
    status TEXT NOT NULL,
    score REAL,
    owners_json TEXT,
    apply_packet_json TEXT,
    outreach_packet_json TEXT,
    research_json TEXT,
    proof_json TEXT,
    notes TEXT,
    description TEXT,
    expectations TEXT,
    pay TEXT,
    posted_at TEXT,
    rejection_json TEXT,
    conflicts_json TEXT,
    stopped INTEGER NOT NULL DEFAULT 0,
    stop_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    created_by_role TEXT,
    PRIMARY KEY (account_id, id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(account_id, status);
CREATE INDEX IF NOT EXISTS idx_jobs_apply_url ON jobs(account_id, apply_url);
CREATE INDEX IF NOT EXISTS idx_jobs_account ON jobs(account_id, updated_at);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    job_id TEXT,
    actor_role TEXT NOT NULL,
    actor TEXT,
    action TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    note TEXT,
    fields_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_job ON events(account_id, job_id);
CREATE INDEX IF NOT EXISTS idx_events_account ON events(account_id, id);

CREATE TABLE IF NOT EXISTS secrets_meta (
    key TEXT PRIMARY KEY,
    value_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    used_at TEXT,
    extra_json TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    track TEXT,
    email TEXT,
    password_hash TEXT,
    display_name TEXT,
    metadata_json TEXT,
    created_by TEXT,
    disabled_at TEXT,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_account_track_display
    ON users(account_id, track, display_name)
    WHERE track IS NOT NULL AND display_name IS NOT NULL
      AND (disabled_at IS NULL OR disabled_at = '');
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_account_email
    ON users(account_id, email) WHERE email IS NOT NULL AND email != '';
CREATE INDEX IF NOT EXISTS idx_users_account ON users(account_id);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen TEXT,
    csrf_hash TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);

CREATE TABLE IF NOT EXISTS invites (
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
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_invites_track ON invites(account_id, track);

CREATE TABLE IF NOT EXISTS queue_items (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    track TEXT,
    job_id TEXT,
    payload_json TEXT,
    status TEXT NOT NULL,
    claimed_by TEXT,
    lease_until TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    dedupe_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_queue_status_kind ON queue_items(account_id, status, kind);
CREATE INDEX IF NOT EXISTS idx_queue_claimed_by ON queue_items(claimed_by);
CREATE INDEX IF NOT EXISTS idx_queue_job ON queue_items(account_id, job_id);
CREATE INDEX IF NOT EXISTS idx_queue_account_status ON queue_items(account_id, status, kind);
CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_account_dedupe
    ON queue_items(account_id, dedupe_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_account_kind_job
    ON queue_items(account_id, kind, job_id)
    WHERE job_id IS NOT NULL AND job_id != '';

CREATE TABLE IF NOT EXISTS people (
    account_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    title TEXT,
    company TEXT,
    job_id TEXT,
    linkedin_url TEXT,
    email TEXT,
    email_confidence TEXT,
    do_not_contact INTEGER NOT NULL DEFAULT 0,
    touches_json TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account_id, id)
);

CREATE INDEX IF NOT EXISTS idx_people_job ON people(account_id, job_id);
CREATE INDEX IF NOT EXISTS idx_people_company ON people(account_id, company);
CREATE INDEX IF NOT EXISTS idx_people_account ON people(account_id, job_id);

CREATE TABLE IF NOT EXISTS hub_blobs (
    account_id TEXT NOT NULL,
    key TEXT NOT NULL,
    content BYTEA NOT NULL,
    content_type TEXT,
    filename TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account_id, key)
);

CREATE TABLE IF NOT EXISTS hub_kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS token_burn (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL DEFAULT 'acc_compat',
    ts TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    skill TEXT,
    lane TEXT,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL,
    duration_ms REAL,
    job_id TEXT,
    actor_role TEXT,
    actor TEXT,
    extra_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_burn_tool ON token_burn(tool_name);
CREATE INDEX IF NOT EXISTS idx_burn_skill ON token_burn(skill);
CREATE INDEX IF NOT EXISTS idx_burn_ts ON token_burn(ts);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    from_user_id TEXT,
    to_user_id TEXT,
    to_track TEXT,
    job_id TEXT,
    type TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_to_user ON messages(to_user_id);
CREATE INDEX IF NOT EXISTS idx_messages_to_track ON messages(to_track);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);

CREATE TABLE IF NOT EXISTS message_reads (
    message_id TEXT NOT NULL,
    reader_key TEXT NOT NULL,
    read_at TEXT NOT NULL,
    PRIMARY KEY (message_id, reader_key)
);

CREATE INDEX IF NOT EXISTS idx_message_reads_reader ON message_reads(reader_key);

CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    pod TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    job_id TEXT,
    company TEXT,
    tags_json TEXT,
    importance INTEGER NOT NULL DEFAULT 2,
    pinned INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_track TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    last_recalled_at TEXT,
    recall_count INTEGER NOT NULL DEFAULT 0,
    solidify_status TEXT NOT NULL DEFAULT 'none',
    recording_id TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_account_pod_hash
    ON memory_items(account_id, pod, content_hash);
CREATE INDEX IF NOT EXISTS idx_memory_pod ON memory_items(pod);
CREATE INDEX IF NOT EXISTS idx_memory_kind ON memory_items(kind);
CREATE INDEX IF NOT EXISTS idx_memory_expires ON memory_items(expires_at);
CREATE INDEX IF NOT EXISTS idx_memory_created_by ON memory_items(created_by, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_recording ON memory_items(recording_id);

CREATE TABLE IF NOT EXISTS skills (
    account_id TEXT NOT NULL,
    id TEXT NOT NULL,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'skill',
    role TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    scope TEXT NOT NULL DEFAULT 'shared',
    owner_user_id TEXT,
    status TEXT NOT NULL DEFAULT 'approved',
    platform TEXT,
    match_json TEXT,
    inputs_json TEXT,
    outputs_json TEXT,
    body_md TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'github',
    origin_ref TEXT,
    parent_skill_id TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    content_hash TEXT NOT NULL,
    reproducible INTEGER NOT NULL DEFAULT 1,
    proctor_status TEXT NOT NULL DEFAULT 'none',
    proctor_note TEXT,
    proctor_evidence_json TEXT,
    approved_at TEXT,
    approved_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    created_by TEXT,
    PRIMARY KEY (account_id, id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_account_shared_slug
    ON skills(account_id, slug) WHERE scope = 'shared';
CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_account_local_slug
    ON skills(account_id, owner_user_id, slug) WHERE scope = 'local';
CREATE INDEX IF NOT EXISTS idx_skills_role_status ON skills(role, status);
CREATE INDEX IF NOT EXISTS idx_skills_owner ON skills(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_skills_origin ON skills(origin);

CREATE TABLE IF NOT EXISTS skill_recordings (
    account_id TEXT NOT NULL,
    id TEXT NOT NULL,
    skill_id TEXT,
    submitted_by TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    queue_item_id TEXT,
    proctor_note TEXT,
    proctor_evidence_json TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (account_id, id)
);

CREATE INDEX IF NOT EXISTS idx_skill_recordings_status ON skill_recordings(account_id, status);
CREATE INDEX IF NOT EXISTS idx_skill_recordings_submitter ON skill_recordings(account_id, submitted_by);

CREATE TABLE IF NOT EXISTS mcps (
    account_id TEXT NOT NULL,
    id TEXT NOT NULL,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'mcp',
    status TEXT NOT NULL DEFAULT 'adopted',
    verdict TEXT,
    capability_json TEXT NOT NULL DEFAULT '[]',
    roles_json TEXT NOT NULL DEFAULT '[]',
    platforms_json TEXT NOT NULL DEFAULT '[]',
    source TEXT,
    install TEXT,
    auth TEXT,
    notes TEXT,
    reason TEXT,
    next_action TEXT,
    config_json TEXT,
    hosted TEXT,
    origin TEXT NOT NULL DEFAULT 'github',
    origin_ref TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account_id, id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mcps_account_slug ON mcps(account_id, slug);
CREATE INDEX IF NOT EXISTS idx_mcps_status ON mcps(status);
CREATE INDEX IF NOT EXISTS idx_mcps_kind ON mcps(kind);
CREATE INDEX IF NOT EXISTS idx_mcps_origin ON mcps(origin);

CREATE TABLE IF NOT EXISTS presence (
    user_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    status TEXT,
    status_hint TEXT,
    last_heartbeat TEXT NOT NULL,
    connected_at TEXT NOT NULL,
    task_id TEXT,
    task_kind TEXT,
    job_id TEXT,
    producing INTEGER NOT NULL DEFAULT 0,
    producing_at TEXT,
    user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_presence_last_heartbeat ON presence(last_heartbeat);

CREATE TABLE IF NOT EXISTS a2a_tasks (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    context_id TEXT NOT NULL,
    state TEXT NOT NULL,
    skill_id TEXT,
    from_user_id TEXT,
    message_id TEXT,
    request_json TEXT,
    result_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_a2a_tasks_context ON a2a_tasks(context_id);
CREATE INDEX IF NOT EXISTS idx_a2a_tasks_state ON a2a_tasks(state);

CREATE TABLE IF NOT EXISTS a2a_peers (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    name TEXT,
    card_url TEXT NOT NULL UNIQUE,
    agent_url TEXT,
    card_json TEXT,
    created_at TEXT NOT NULL,
    last_ok_at TEXT
);
