"""Tenant schema: accounts table + account_id on every namespaced table.

Locality: one Module owns the column, backfill, and unique-index rewrite so
callers never sprinkle ALTER TABLE.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.constants import TRACKS
from app.sql import column_names
from app.tenant import COMPAT_ACCOUNT_ID, COMPAT_USERNAME

ACCOUNTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    tracks_json TEXT NOT NULL DEFAULT '[]'
);
"""

# Tables that must be airgapped per account. Secrets_meta stays process-global
# (bootstrap token). hub_kv stays process-global (deploy metadata).
TENANT_TABLES = (
    "jobs",
    "events",
    "users",
    "sessions",
    "api_keys",
    "invites",
    "queue_items",
    "people",
    "token_burn",
    "messages",
    "memory_items",
    "skills",
    "skill_recordings",
    "mcps",
    "presence",
    "a2a_tasks",
    "a2a_peers",
    "hub_blobs",
)


def ensure_tenant_schema(conn: Any) -> None:
    conn.executescript(ACCOUNTS_SCHEMA)
    for table in TENANT_TABLES:
        _ensure_account_id_column(conn, table)
    _ensure_compat_account(conn)
    _rekey_unique_indexes(conn)


def _ensure_account_id_column(conn: Any, table: str) -> None:
    try:
        cols = column_names(conn, table)
    except Exception:
        return
    if not cols:
        return
    if "account_id" in cols:
        return
    conn.execute(
        f"ALTER TABLE {table} ADD COLUMN account_id TEXT NOT NULL DEFAULT '{COMPAT_ACCOUNT_ID}'"
    )
    conn.execute(
        f"UPDATE {table} SET account_id = ? WHERE account_id IS NULL OR account_id = ''",
        (COMPAT_ACCOUNT_ID,),
    )


def _ensure_compat_account(conn: Any) -> None:
    cur = conn.execute("SELECT id FROM accounts WHERE id = ?", (COMPAT_ACCOUNT_ID,))
    if cur.fetchone():
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """
        INSERT INTO accounts (id, username, password_hash, created_at, tracks_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            COMPAT_ACCOUNT_ID,
            COMPAT_USERNAME,
            "!compat-unusable",
            now,
            json.dumps(list(TRACKS), ensure_ascii=False),
        ),
    )


def _rekey_unique_indexes(conn: Any) -> None:
    """Scope uniqueness to account_id. Old global uniques would leak across tenants."""
    drops = (
        "idx_skills_shared_slug",
        "idx_skills_local_slug",
        "idx_mcps_slug",
        "idx_queue_kind_job",
        "idx_users_track_display",
        "idx_users_email",
        "idx_memory_pod_hash",
    )
    for name in drops:
        conn.execute(f"DROP INDEX IF EXISTS {name}")
    if column_names(conn, "queue_items"):
        conn.execute("ALTER TABLE queue_items DROP CONSTRAINT IF EXISTS queue_items_dedupe_key_key")
    by_table = {
        "skills": """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_account_shared_slug
                ON skills(account_id, slug) WHERE scope = 'shared';
            CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_account_local_slug
                ON skills(account_id, owner_user_id, slug) WHERE scope = 'local';
        """,
        "mcps": """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mcps_account_slug
                ON mcps(account_id, slug);
        """,
        "queue_items": """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_account_dedupe
                ON queue_items(account_id, dedupe_key);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_account_kind_job
                ON queue_items(account_id, kind, job_id)
                WHERE job_id IS NOT NULL AND job_id != '';
            CREATE INDEX IF NOT EXISTS idx_queue_account_status
                ON queue_items(account_id, status, kind);
        """,
        "users": """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_account_track_display
                ON users(account_id, track, display_name)
                WHERE track IS NOT NULL AND display_name IS NOT NULL
                  AND (disabled_at IS NULL OR disabled_at = '');
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_account_email
                ON users(account_id, email) WHERE email IS NOT NULL AND email != '';
            CREATE INDEX IF NOT EXISTS idx_users_account ON users(account_id);
        """,
        "memory_items": """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_account_pod_hash
                ON memory_items(account_id, pod, content_hash);
        """,
        "jobs": """
            CREATE INDEX IF NOT EXISTS idx_jobs_account ON jobs(account_id, updated_at);
        """,
        "events": """
            CREATE INDEX IF NOT EXISTS idx_events_account ON events(account_id, id);
        """,
        "people": """
            CREATE INDEX IF NOT EXISTS idx_people_account ON people(account_id, job_id);
        """,
    }
    for table, sql in by_table.items():
        if column_names(conn, table):
            conn.executescript(sql)
