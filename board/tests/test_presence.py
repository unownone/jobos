"""Phase C: heartbeat, presence statuses, admin directory. No API keys in payloads."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import require_principal
from app.constants import ROLES
from app.main import create_app
from app.presence import STALE_AFTER_S, derive_status, format_last_active, mount_presence
from app.settings import Settings

TOKENS = {role: f"test-token-{role}-not-real" for role in ROLES}


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        board_dir=tmp_path,
        db_path=tmp_path / "board.db",
        host="127.0.0.1",
        port=8787,
        tokens=dict(TOKENS),
        public_url="https://hub.example.test",
        bootstrap_token="",
        env_path=tmp_path / ".env",
        tokens_json_path=tmp_path / "tokens.local.json",
    )


@pytest.fixture()
def hub(tmp_path: Path) -> tuple[TestClient, Settings, Clock]:
    settings = _settings(tmp_path)
    app = create_app(settings)
    mount_presence(app, app.state.db, require_principal(settings, app.state.db))
    clock = Clock()
    app.state.clock = clock
    return TestClient(app), settings, clock


def csrf_headers(client: TestClient, extra: dict[str, str] | None = None) -> dict[str, str]:
    csrf = client.cookies.get("hub_csrf") or ""
    headers = {"X-CSRF": csrf, "Content-Type": "application/json"}
    if extra:
        headers.update(extra)
    return headers


def bootstrap_admin(client: TestClient) -> None:
    token = client.app.state.bootstrap_token
    res = client.post(
        "/api/auth/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "owner@example.test", "password": "correct-horse"},
    )
    assert res.status_code == 200, res.text


def invite_join(
    client: TestClient,
    *,
    track: str,
    display_name: str,
    metadata: dict | None = None,
) -> dict:
    created = client.post(
        "/api/invites",
        headers=csrf_headers(client),
        json={"track": track, "max_redemptions": 8, "ttl_hours": 72, "mode": "owner_then_agents"},
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    joined = client.post(
        "/api/auth/join",
        json={
            "invite_id": payload["invite"]["id"],
            "s": payload["secret"],
            "display_name": display_name,
            "metadata": metadata
            or {
                "model": "grok-4",
                "harness": "cursor-cloud",
                "bed": "cursor",
            },
        },
    )
    assert joined.status_code == 200, joined.text
    return joined.json()


def test_heartbeat_unauthenticated_401(hub: tuple[TestClient, Settings, Clock]) -> None:
    client, _settings, _clock = hub
    res = client.post("/api/presence/heartbeat", json={"status_hint": "logged_in"})
    assert res.status_code == 401


def test_heartbeat_logged_in_then_stale(hub: tuple[TestClient, Settings, Clock]) -> None:
    client, _settings, clock = hub
    bootstrap_admin(client)
    ping = client.post(
        "/api/presence/heartbeat",
        headers=csrf_headers(client),
        json={"status_hint": "logged_in"},
    )
    assert ping.status_code == 200, ping.text
    body = ping.json()
    assert body["status"] == "logged_in"
    assert body["heartbeat_s"] == 10
    assert body["stale_after_s"] == 300
    assert body["last_active"].startswith("Last active:")
    assert "just now" in body["last_active"]
    assert body["pending_messages"] == 0
    assert set(body) == {
        "ok",
        "status",
        "heartbeat_s",
        "stale_after_s",
        "last_seen",
        "last_active",
        "pending_messages",
        "memory",
        "candidate_revision",
        "candidate_onboarded",
        "self",
    }
    assert set(body["self"]) == {
        "user_id",
        "display_name",
        "track",
        "kind",
        "role",
        "model",
        "harness",
        "bed",
        "last_seen",
        "last_active",
        "status",
        "current_task",
    }
    assert "api_key" not in str(body).lower()
    listed = client.get("/api/presence")
    assert listed.status_code == 200
    users = listed.json()["users"]
    assert any(u["status"] == "logged_in" for u in users)
    assert any((u.get("last_active") or "").startswith("Last active:") for u in users)
    clock.advance(STALE_AFTER_S + 1)
    stale = client.get("/api/presence")
    assert stale.status_code == 200
    stale_users = stale.json()["users"]
    statuses = {u["user_id"]: u["status"] for u in stale_users}
    admin_id = client.get("/api/auth/me").json()["user_id"]
    assert statuses[admin_id] == "stale"
    stale_row = next(u for u in stale_users if u["user_id"] == admin_id)
    assert stale_row["last_active"] == "Last active: 5m ago"


def test_idle_after_sixty_seconds_of_heartbeats(
    hub: tuple[TestClient, Settings, Clock],
) -> None:
    client, _settings, clock = hub
    bootstrap_admin(client)
    client.post("/api/presence/heartbeat", headers=csrf_headers(client), json={"status_hint": "logged_in"})
    for _ in range(7):
        clock.advance(10)
        again = client.post(
            "/api/presence/heartbeat",
            headers=csrf_headers(client),
            json={"status_hint": "logged_in"},
        )
        assert again.status_code == 200, again.text
    assert again.json()["status"] == "idle"


def test_working_and_producing_hints(hub: tuple[TestClient, Settings, Clock]) -> None:
    client, _settings, _clock = hub
    bootstrap_admin(client)
    owner = invite_join(client, track="discovery", display_name="disc-owner")
    key = owner["api_key"]
    headers = {"Authorization": f"Bearer {key}"}
    working = client.post(
        "/api/presence/heartbeat",
        headers=headers,
        json={"status_hint": "working", "task_id": "board__acme-swe", "task_kind": "job", "job_id": "board__acme-swe"},
    )
    assert working.status_code == 200, working.text
    assert working.json()["status"] == "working"
    assert working.json()["self"]["current_task"]["id"] == "board__acme-swe"
    producing = client.post(
        "/api/presence/heartbeat",
        headers=headers,
        json={"status_hint": "working", "producing": True, "task_id": "board__acme-swe"},
    )
    assert producing.json()["status"] == "producing"
    hint_producing = client.post(
        "/api/presence/heartbeat",
        headers=headers,
        json={"status_hint": "producing", "task_id": "opaque-1"},
    )
    assert hint_producing.json()["status"] == "producing"
    logged = client.post(
        "/api/presence/heartbeat",
        headers=headers,
        json={"status_hint": "logged_in", "producing": True},
    )
    assert logged.json()["status"] == "logged_in"


def test_keys_never_in_presence_payload(hub: tuple[TestClient, Settings, Clock]) -> None:
    client, _settings, _clock = hub
    bootstrap_admin(client)
    owner = invite_join(
        client,
        track="application",
        display_name="apply-owner",
        metadata={
            "model": "claude",
            "harness": "cursor",
            "bed": "local",
            "api_key": "jh_agt_should_not_leak_xxxxx",
            "token": "role-token-secret",
        },
    )
    key = owner["api_key"]
    assert key.startswith("jh_")
    client.post(
        "/api/presence/heartbeat",
        headers={"Authorization": f"Bearer {key}"},
        json={"status_hint": "logged_in"},
    )
    listed = client.get("/api/presence")
    blob = listed.text
    assert key not in blob
    assert "jh_agt_should_not_leak" not in blob
    assert "role-token-secret" not in blob
    assert "password_hash" not in blob
    assert "key_hash" not in blob
    row = next(u for u in listed.json()["users"] if u["display_name"] == "apply-owner")
    assert row["model"] == "claude"
    assert row["harness"] == "cursor"
    assert row["bed"] == "local"
    assert row["kind"] == "owner"
    assert row["track"] == "application"
    assert "api_key" not in row


def test_owner_sees_own_track_only(hub: tuple[TestClient, Settings, Clock]) -> None:
    client, _settings, _clock = hub
    bootstrap_admin(client)
    disc = invite_join(client, track="discovery", display_name="d-owner")
    out = invite_join(client, track="outreach", display_name="o-owner")
    client.post(
        "/api/presence/heartbeat",
        headers={"Authorization": f"Bearer {disc['api_key']}"},
        json={"status_hint": "logged_in"},
    )
    client.post(
        "/api/presence/heartbeat",
        headers={"Authorization": f"Bearer {out['api_key']}"},
        json={"status_hint": "working"},
    )
    as_disc = client.get("/api/presence", headers={"Authorization": f"Bearer {disc['api_key']}"})
    assert as_disc.status_code == 200
    names = {u["display_name"] for u in as_disc.json()["users"]}
    assert "d-owner" in names
    assert "o-owner" not in names
    agent = client.post(
        "/api/agents",
        headers={"Authorization": f"Bearer {disc['api_key']}"},
        json={"display_name": "d-agent", "metadata": {"model": "gpt"}},
    )
    assert agent.status_code == 200
    agent_key = agent.json()["api_key"]
    client.post(
        "/api/presence/heartbeat",
        headers={"Authorization": f"Bearer {agent_key}"},
        json={"status_hint": "idle"},
    )
    forbidden = client.get("/api/presence", headers={"Authorization": f"Bearer {agent_key}"})
    assert forbidden.status_code == 403


def test_admin_users_directory_and_page(hub: tuple[TestClient, Settings, Clock]) -> None:
    client, _settings, _clock = hub
    bootstrap_admin(client)
    invite_join(client, track="maintenance", display_name="hygiene-owner")
    listed = client.get("/api/users")
    assert listed.status_code == 200
    blob = listed.text
    assert "jh_own_" not in blob
    assert "jh_agt_" not in blob
    ids = {u["display_name"] for u in listed.json()["users"]}
    assert "hygiene-owner" in ids
    page = client.get("/admin/users")
    assert page.status_code == 200
    assert "Directory" in page.text


def test_presence_detail_includes_memories_tools_and_events(
    hub: tuple[TestClient, Settings, Clock],
) -> None:
    client, _settings, _clock = hub
    bootstrap_admin(client)
    disc = invite_join(client, track="discovery", display_name="scout-bot")
    key = disc["api_key"]
    headers = {"Authorization": f"Bearer {key}"}
    client.post("/api/presence/heartbeat", headers=headers, json={"status_hint": "working", "job_id": "gh__1", "task_id": "gh__1", "task_kind": "job"})
    mem = client.post(
        "/api/memory/items",
        headers=headers,
        json={
            "pod": "track",
            "kind": "portal_quirk",
            "title": "Greenhouse work-auth radio",
            "body": (
                "Acme Greenhouse asks a work-authorization radio that is missing from the "
                "apply packet. Bounce to discovery instead of guessing the legal answer."
            ),
            "company": "Acme",
        },
    )
    assert mem.status_code in {200, 201}, mem.text
    burn = client.post(
        "/api/metrics/token_burn",
        headers=headers,
        json={"tool_name": "exa-mcp", "skill": "discovery", "prompt_tokens": 11, "completion_tokens": 4},
    )
    assert burn.status_code == 201, burn.text
    listed = client.get("/api/presence")
    row = next(u for u in listed.json()["users"] if u["display_name"] == "scout-bot")
    detail = client.get(f"/api/presence/{row['user_id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["user"]["display_name"] == "scout-bot"
    assert any(m["title"] == "Greenhouse work-auth radio" for m in body["memories"])
    assert any(t["tool_name"] == "exa-mcp" for t in body["tools"])
    assert "jh_agt_" not in detail.text
    missing = client.get("/api/presence/does-not-exist")
    assert missing.status_code == 404
    as_owner = client.post(
        "/api/auth/join",
        json={
            "invite_id": "nope",
            "s": "nope",
            "display_name": "x",
        },
    )
    assert as_owner.status_code in {401, 404}


def test_compat_connect_can_heartbeat(hub: tuple[TestClient, Settings, Clock]) -> None:
    client, _settings, _clock = hub
    res = client.post(
        "/api/presence/heartbeat",
        headers={"X-Role": "admin", "X-Token": TOKENS["admin"], "X-Actor": "compat-admin"},
        json={"status_hint": "logged_in"},
    )
    assert res.status_code == 200, res.text
    listed = client.get(
        "/api/presence",
        headers={"X-Role": "admin", "X-Token": TOKENS["admin"]},
    )
    assert listed.status_code == 200
    kinds = {u["kind"] for u in listed.json()["users"]}
    assert "compat" in kinds


def test_derive_status_unit() -> None:
    now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
    hb = now - timedelta(seconds=5)
    assert (
        derive_status(
            last_heartbeat=hb,
            connected_at=now - timedelta(seconds=10),
            status_hint="logged_in",
            producing_flag=False,
            has_claim=False,
            recent_write=False,
            now=now,
        )
        == "logged_in"
    )
    assert (
        derive_status(
            last_heartbeat=now - timedelta(seconds=301),
            connected_at=now - timedelta(seconds=40),
            status_hint="working",
            producing_flag=True,
            has_claim=True,
            recent_write=True,
            now=now,
        )
        == "stale"
    )
    assert (
        derive_status(
            last_heartbeat=hb,
            connected_at=now - timedelta(seconds=70),
            status_hint=None,
            producing_flag=False,
            has_claim=False,
            recent_write=False,
            now=now,
        )
        == "idle"
    )
    assert (
        derive_status(
            last_heartbeat=hb,
            connected_at=hb,
            status_hint="working",
            producing_flag=False,
            has_claim=False,
            recent_write=True,
            now=now,
        )
        == "producing"
    )
    assert (
        derive_status(
            last_heartbeat=now - timedelta(seconds=31),
            connected_at=now - timedelta(seconds=40),
            status_hint="working",
            producing_flag=True,
            has_claim=True,
            recent_write=True,
            now=now,
        )
        == "producing"
    )


def test_format_last_active_unit() -> None:
    now = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
    assert format_last_active(None, now) is None
    assert format_last_active(now - timedelta(seconds=3), now) == "Last active: just now"
    assert format_last_active(now - timedelta(seconds=12), now) == "Last active: 12s ago"
    assert format_last_active(now - timedelta(seconds=301), now) == "Last active: 5m ago"
    assert format_last_active(now - timedelta(hours=2), now) == "Last active: 2h ago"
    assert (
        format_last_active(now - timedelta(days=2), now) == "Last active: 2026-09-18 12:00 UTC"
    )


def test_api_action_is_heartbeat_without_manual_ping(
    hub: tuple[TestClient, Settings, Clock],
) -> None:
    client, _settings, clock = hub
    bootstrap_admin(client)
    owner = invite_join(client, track="discovery", display_name="auto-bot")
    key = owner["api_key"]
    before = client.get("/api/presence")
    assert all(u["display_name"] != "auto-bot" for u in before.json()["users"])
    meta = client.get("/api/whoami", headers={"Authorization": f"Bearer {key}"})
    assert meta.status_code == 200, meta.text
    listed = client.get("/api/presence")
    row = next(u for u in listed.json()["users"] if u["display_name"] == "auto-bot")
    assert row["status"] in {"logged_in", "idle", "working", "producing"}
    assert row["last_active"] == "Last active: just now"
    clock.advance(STALE_AFTER_S - 10)
    still = client.get("/api/presence")
    live = next(u for u in still.json()["users"] if u["display_name"] == "auto-bot")
    assert live["status"] != "stale"
    clock.advance(20)
    stale = client.get("/api/presence")
    gone = next(u for u in stale.json()["users"] if u["display_name"] == "auto-bot")
    assert gone["status"] == "stale"
    assert gone["last_active"] == "Last active: 5m ago"


def test_job_write_marks_agent_producing(
    hub: tuple[TestClient, Settings, Clock],
) -> None:
    client, _settings, _clock = hub
    bootstrap_admin(client)
    owner = invite_join(client, track="discovery", display_name="writer-bot")
    key = owner["api_key"]
    created = client.post(
        "/api/jobs",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "id": "auto__presence",
            "company": "Acme",
            "title": "Staff",
            "status": "discovered",
        },
    )
    assert created.status_code == 201, created.text
    listed = client.get("/api/presence")
    row = next(u for u in listed.json()["users"] if u["display_name"] == "writer-bot")
    assert row["status"] == "producing"
    assert row["last_active"].startswith("Last active:")


def test_presence_list_does_not_refresh_other_agents(
    hub: tuple[TestClient, Settings, Clock],
) -> None:
    client, _settings, clock = hub
    bootstrap_admin(client)
    owner = invite_join(client, track="discovery", display_name="quiet-bot")
    key = owner["api_key"]
    client.get("/api/whoami", headers={"Authorization": f"Bearer {key}"})
    clock.advance(STALE_AFTER_S + 1)
    listed = client.get("/api/presence")
    row = next(u for u in listed.json()["users"] if u["display_name"] == "quiet-bot")
    assert row["status"] == "stale"
    listed_again = client.get("/api/presence")
    row_again = next(u for u in listed_again.json()["users"] if u["display_name"] == "quiet-bot")
    assert row_again["status"] == "stale"


def test_load_users_by_ids_chunks_instead_of_querying_each_id() -> None:
    from app.storage.repos.presence import load_users_by_ids
    from app.storage.sqlite import SqliteDatabase

    db = SqliteDatabase(":memory:")
    db.execute("CREATE TABLE users (id TEXT PRIMARY KEY, kind TEXT)")
    ids = [f"usr_{i}" for i in range(101)]
    db.queries.reset()
    assert load_users_by_ids(db, []) == {}
    assert db.queries.count == 0
    db.queries.reset()
    assert load_users_by_ids(db, ["usr_1", "usr_1", "usr_2"]) == {}
    assert db.queries.count == 1
    db.queries.reset()
    assert load_users_by_ids(db, ids) == {}
    assert db.queries.count == 2


def test_directory_listing_does_not_query_once_per_user() -> None:
    from app.auth import Principal
    from app.presence import directory_rows
    from app.storage.sqlite import SqliteDatabase

    db = SqliteDatabase(":memory:")
    db.execute(
        """
        CREATE TABLE presence (
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
        )
        """
    )
    db.execute(
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            account_id TEXT,
            kind TEXT,
            track TEXT,
            email TEXT,
            password_hash TEXT,
            display_name TEXT,
            metadata_json TEXT,
            created_by TEXT,
            disabled_at TEXT,
            created_at TEXT
        )
        """
    )
    db.execute(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            last_seen TEXT,
            expires_at TEXT
        )
        """
    )
    db.execute(
        """
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            account_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            job_id TEXT,
            actor TEXT
        )
        """
    )
    account = "acc_dir"
    other = "acc_other"
    stamp = "2026-09-07T12:00:00Z"
    db.execute(
        """
        INSERT INTO events (account_id, ts, job_id, actor)
        VALUES (?, ?, ?, ?)
        """,
        (account, stamp, "job-1", "usr_work"),
    )
    people = [
        ("usr_work", account, "agent", "discovery", "Writer", None),
        ("usr_viewer", account, "viewer", None, "Pat", None),
        ("usr_disabled", account, "admin", None, "Gone", stamp),
        ("usr_agent_only", account, "agent", "discovery", "Lurker", None),
        ("usr_other", other, "agent", "discovery", "Outsider", None),
    ]
    for index in range(10):
        people.append((f"usr_{index}", account, "agent", "discovery", f"bot-{index}", None))
    for user_id, account_id, kind, track, name, disabled in people:
        db.execute(
            """
            INSERT INTO users (
                id, account_id, kind, track, email, password_hash, display_name,
                metadata_json, created_by, disabled_at, created_at
            ) VALUES (?, ?, ?, ?, NULL, NULL, ?, '{}', NULL, ?, ?)
            """,
            (user_id, account_id, kind, track, name, disabled, stamp),
        )
    present = ["usr_work", *[f"usr_{index}" for index in range(10)]]
    for user_id in present:
        hint = "working" if user_id == "usr_work" else "logged_in"
        db.execute(
            """
            INSERT INTO presence (
                user_id, account_id, status, status_hint, last_heartbeat, connected_at,
                task_id, task_kind, job_id, producing, producing_at, user_agent
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, NULL, '')
            """,
            (user_id, account, hint, hint, stamp, stamp),
        )
    db.execute(
        """
        INSERT INTO presence (
            user_id, account_id, status, status_hint, last_heartbeat, connected_at,
            task_id, task_kind, job_id, producing, producing_at, user_agent
        ) VALUES ('compat:discovery:ghost', ?, 'logged_in', 'logged_in', ?, ?, NULL, NULL, NULL, 0, NULL, '')
        """,
        (account, stamp, stamp),
    )
    db.execute(
        """
        INSERT INTO presence (
            user_id, account_id, status, status_hint, last_heartbeat, connected_at,
            task_id, task_kind, job_id, producing, producing_at, user_agent
        ) VALUES ('usr_other', ?, 'logged_in', 'logged_in', ?, ?, NULL, NULL, NULL, 0, NULL, '')
        """,
        (other, stamp, stamp),
    )
    for session_id, user_id, account_id in (
        ("sess_view", "usr_viewer", account),
        ("sess_disabled", "usr_disabled", account),
        ("sess_agent", "usr_agent_only", account),
        ("sess_other", "usr_other", other),
    ):
        db.execute(
            """
            INSERT INTO sessions (id, account_id, user_id, last_seen, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, account_id, user_id, stamp, stamp),
        )
    principal = Principal(
        role="admin",
        actor="Ada",
        user_id="usr_admin",
        track=None,
        kind="admin",
        auth="session",
        account_id=account,
    )
    seen: list[str] = []
    original = db._execute

    def spy(sql: str, params: tuple = (), *, guarded: bool = False):
        seen.append(" ".join(sql.split()).lower())
        return original(sql, params, guarded=guarded)

    db._execute = spy
    now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    rows = directory_rows(db, principal, now)
    by_name = {row["display_name"]: row for row in rows}
    assert by_name["Writer"]["status"] == "producing"
    assert by_name["bot-0"]["status"] == "logged_in"
    assert by_name["Pat"]["status"] == "logged_in"
    assert by_name["ghost"]["kind"] == "compat"
    assert "Outsider" not in by_name
    assert "Gone" not in by_name
    assert "Lurker" not in by_name
    user_sql = [sql for sql in seen if "from users" in sql]
    event_sql = [sql for sql in seen if "from events" in sql]
    assert len(user_sql) == 1
    assert " in (" in user_sql[0]
    assert "id = ?" not in user_sql[0]
    assert len(event_sql) == 1
    assert "limit 1" not in event_sql[0]
    assert any("from presence" in sql and "order by last_heartbeat desc" in sql for sql in seen)
    assert len(seen) < len(present)


def test_presence_http_list_does_not_query_per_user(
    hub: tuple[TestClient, Settings, Clock],
) -> None:
    from app.presence import iso_z, upsert_presence_row
    from app.tenant import TenantContext

    client, _settings, clock = hub
    bootstrap_admin(client)
    db = client.app.state.db
    admin_id = client.get("/api/auth/me").json()["user_id"]
    admin = db.get_user(admin_id)
    tenant = TenantContext(admin["account_id"])
    stamp = iso_z(clock.now)
    for index in range(12):
        user = db.insert_user(
            user_id=f"usr_batch_{index}",
            kind="agent",
            track="discovery",
            email=None,
            password_hash=None,
            display_name=f"batch-{index}",
            metadata={"model": "m", "harness": "h", "bed": "b"},
            created_by=admin_id,
            account_id=admin["account_id"],
        )
        upsert_presence_row(
            db,
            user_id=user["id"],
            status="logged_in",
            status_hint="logged_in",
            last_heartbeat=stamp,
            connected_at=stamp,
            task_id=None,
            task_kind=None,
            job_id=None,
            producing=False,
            producing_at=None,
            user_agent="test",
            tenant=tenant,
        )
    calls: list[str] = []
    original = db.conn.execute

    def wrapped(sql, params=()):
        calls.append(" ".join(str(sql).split()).lower())
        return original(sql, params)

    db.conn.execute = wrapped
    try:
        listed = client.get("/api/presence")
    finally:
        db.conn.execute = original
    assert listed.status_code == 200, listed.text
    names = {row["display_name"] for row in listed.json()["users"]}
    assert {f"batch-{index}" for index in range(12)} <= names
    user_sql = [sql for sql in calls if "from users" in sql]
    point = [sql for sql in user_sql if " in (" not in sql]
    batched = [sql for sql in user_sql if " in (" in sql]
    event_limits = [sql for sql in calls if "from events" in sql and "limit 1" in sql]
    assert len(batched) == 1
    assert len(point) < 12
    assert event_limits == []
