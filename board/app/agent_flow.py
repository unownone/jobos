"""Agent-first flow: one MCP connection, lanes the agent records, loops it keeps running.

Humans observe and steer. The agent asks which lanes this session runs and
stores that choice here. jobOS does not pick the lanes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from app.bootstrap import new_id, sha256_hex
from app.db import BoardDB, utc_now
from app.tenant import TenantContext

LANES = ("find", "apply", "outreach")
LANE_ALIASES = {
    "find": "find",
    "discovery": "find",
    "source": "find",
    "apply": "apply",
    "application": "apply",
    "outreach": "outreach",
}
LANE_NEEDS = {
    "find": ("browser",),
    "apply": ("browser",),
    "outreach": ("email",),
}
LANE_SKILL = {
    "find": "job-discovery",
    "apply": "job-apply",
    "outreach": "job-outreach",
}
FIND_SHORTLIST = frozenset({"shortlisted", "apply_ready"})
FIND_CAP = 12
APPLY_OPEN = ("apply_ready", "applying")
OUTREACH_OPEN = ("outreach_ready", "applied")

ACCESS_PREFIX = "jhmcp_at_"
REFRESH_PREFIX = "jhmcp_rt_"
CLIENT_PREFIX = "jhmcp_cid_"
CODE_PREFIX = "jhmcp_cd_"
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=90)
CODE_TTL = timedelta(minutes=10)
SCOPE = "jobos"

SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_oauth_clients (
    client_id TEXT PRIMARY KEY,
    client_name TEXT NOT NULL,
    redirect_uris_json TEXT NOT NULL,
    auth_method TEXT NOT NULL,
    secret_hash TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mcp_auth_codes (
    code_hash TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    scope TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mcp_grants (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    client_name TEXT NOT NULL,
    access_hash TEXT NOT NULL UNIQUE,
    refresh_hash TEXT NOT NULL,
    previous_refresh_hash TEXT,
    access_expires_at TEXT NOT NULL,
    refresh_expires_at TEXT NOT NULL,
    scope TEXT NOT NULL,
    session_id TEXT,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_mcp_grants_account ON mcp_grants(account_id, created_at);

CREATE TABLE IF NOT EXISTS mcp_spent_refreshes (
    grant_id TEXT NOT NULL,
    refresh_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (grant_id, refresh_hash)
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    grant_id TEXT NOT NULL,
    label TEXT NOT NULL,
    lanes_json TEXT NOT NULL DEFAULT '[]',
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_grant ON agent_sessions(account_id, grant_id, status);

CREATE TABLE IF NOT EXISTS agent_loops (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    lane TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    step INTEGER NOT NULL DEFAULT 0,
    cursor_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_loops_session ON agent_loops(account_id, session_id, status);

CREATE TABLE IF NOT EXISTS agent_uses (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    slug TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_uses_session ON agent_uses(account_id, session_id, created_at);

CREATE TABLE IF NOT EXISTS agent_steers (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    session_id TEXT,
    author_user_id TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_steers_account ON agent_steers(account_id, created_at);
"""


def ensure_agent_flow_schema(conn: Any) -> None:
    conn.executescript(SCHEMA)


def _iso_after(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(raw: Any, fallback: Any) -> Any:
    if raw is None or raw == "":
        return fallback
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def normalize_lane(raw: str) -> str | None:
    key = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    return LANE_ALIASES.get(key)


def empty_capabilities() -> dict[str, Any]:
    return {"browser": False, "email": False, "reported": False}


def normalize_capabilities(raw: dict[str, Any] | None, *, reported: bool) -> dict[str, Any]:
    data = raw or {}
    return {
        "browser": bool(data.get("browser")),
        "email": bool(data.get("email")),
        "reported": reported,
    }


def evaluate_lane(session: dict[str, Any], lane: str) -> dict[str, Any]:
    """Decide if this agent session can run a lane. Unreported capabilities cannot."""
    canonical = normalize_lane(lane)
    lanes = list(session.get("lanes") or [])
    caps = session.get("capabilities") or empty_capabilities()
    if canonical is None:
        return {
            "can": False,
            "lane": lane,
            "reason": "unknown_lane",
            "missing": [],
            "lanes": lanes,
            "instruction": "Lanes are find, apply, and outreach. Ask the human which of those this session should run.",
        }
    if not lanes:
        return {
            "can": False,
            "lane": canonical,
            "reason": "lanes_unset",
            "missing": ["session_lanes"],
            "lanes": [],
            "instruction": (
                "Ask the human which lanes this session should run: find, apply, outreach. "
                "They may pick more than one. Then call set_session_lanes. Do not pick for them."
            ),
        }
    if canonical not in lanes:
        return {
            "can": False,
            "lane": canonical,
            "reason": "lane_not_in_session",
            "missing": ["session_lanes"],
            "lanes": lanes,
            "instruction": (
                f"This session is running {', '.join(lanes)}. "
                f"Ask the human before adding {canonical}, then call set_session_lanes with the full set."
            ),
        }
    if not caps.get("reported"):
        needs = list(LANE_NEEDS[canonical])
        return {
            "can": False,
            "lane": canonical,
            "reason": "capabilities_not_reported",
            "missing": needs,
            "lanes": lanes,
            "instruction": (
                "Call report_capabilities with the truth for this client. "
                "browser is true only when you can drive a real browser. "
                "email is true only when a mailbox is connected. Then call evaluate_lane again."
            ),
        }
    missing = [need for need in LANE_NEEDS[canonical] if not caps.get(need)]
    if missing:
        hint = {
            "browser": "Find and apply need a browser in this client. Say so to the human and stop this lane.",
            "email": "Outreach needs a connected mailbox. Say so to the human and stop this lane.",
        }
        return {
            "can": False,
            "lane": canonical,
            "reason": "missing_" + "_".join(missing),
            "missing": missing,
            "lanes": lanes,
            "capabilities": caps,
            "instruction": " ".join(hint[item] for item in missing),
        }
    return {
        "can": True,
        "lane": canonical,
        "reason": "ready",
        "missing": [],
        "lanes": lanes,
        "capabilities": caps,
        "skill": LANE_SKILL[canonical],
        "instruction": f"You can run {canonical}. Read {LANE_SKILL[canonical]} and start_loop if you have not already.",
    }


def skill_lane(skill: dict[str, Any]) -> str | None:
    tags = {str(tag).lower() for tag in (skill.get("tags") or [])}
    role = str(skill.get("role") or "").lower()
    if "source" in tags or role == "discovery":
        return "find"
    if "apply" in tags or role == "apply":
        return "apply"
    if "outreach" in tags or role == "outreach":
        return "outreach"
    if "research" in tags or role == "research":
        return "find"
    return None


def capability_preface(lane: str | None) -> str:
    if lane is None:
        return (
            "## Session\n\n"
            "If this client is on jobOS MCP, call get_started first. "
            "Ask the human which lanes this session runs before hunt work.\n"
        )
    needs = ", ".join(LANE_NEEDS[lane])
    return (
        f"## Capability gate\n\n"
        f"This playbook is the `{lane}` lane. Before any step below, call `evaluate_lane` "
        f"with `{lane}`. It needs: {needs}. "
        "Find and apply stop without a browser. Outreach stops without a connected mailbox. "
        "If `can` is false, tell the human what is missing and stop. "
        "If session lanes are empty, ask which lanes this session should run "
        "(find, apply, outreach — more than one is allowed) and call `set_session_lanes`. "
        "You are one agent. You are not locked to a single lane unless the human says so.\n"
    )


def redirect_uri_allowed(uri: str) -> bool:
    text = (uri or "").strip()
    if not text or len(text) > 500 or any(ch in text for ch in ("\n", "\r", " ")):
        return False
    parsed = urlparse(text)
    if parsed.fragment:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme in {"javascript", "data", "file", "vbscript"}:
        return False
    if parsed.scheme == "https" and host:
        return True
    if parsed.scheme == "http" and host in {"127.0.0.1", "localhost", "::1"}:
        return True
    if parsed.scheme and parsed.scheme not in {"http", "https"} and (parsed.netloc or parsed.path):
        return True
    return False


_PKCE_VERIFIER = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


def pkce_verifier_ok(verifier: str) -> bool:
    """RFC 7636: 43–128 unreserved ASCII characters."""
    return bool(_PKCE_VERIFIER.fullmatch(verifier or ""))


def pkce_s256(verifier: str) -> str:
    raw = verifier.encode("ascii")
    digest = hashlib.sha256(raw).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


class AgentFlow:
    def __init__(self, db: BoardDB) -> None:
        self.db = db
        ensure_agent_flow_schema(db.conn)

    def register_client(
        self,
        *,
        client_name: str,
        redirect_uris: list[str],
        auth_method: str,
    ) -> dict[str, Any]:
        name = (client_name or "AI client").strip()[:120] or "AI client"
        method = auth_method if auth_method in {"none", "client_secret_post"} else ""
        if not method:
            raise ValueError("token_endpoint_auth_method must be none or client_secret_post")
        uris = []
        for uri in redirect_uris:
            text = str(uri).strip()
            if not redirect_uri_allowed(text):
                raise ValueError(f"redirect_uri is not allowed: {text}")
            if text not in uris:
                uris.append(text)
        if not uris:
            raise ValueError("redirect_uris is required")
        client_id = CLIENT_PREFIX + secrets.token_urlsafe(24)
        secret = None
        secret_hash = None
        if method == "client_secret_post":
            secret = "jhmcp_cs_" + secrets.token_urlsafe(32)
            secret_hash = sha256_hex(secret)
        now = utc_now()
        self.db.conn.execute(
            """
            INSERT INTO mcp_oauth_clients (
                client_id, client_name, redirect_uris_json, auth_method, secret_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (client_id, name, _dump(uris), method, secret_hash, now),
        )
        self.db.conn.commit()
        out = {
            "client_id": client_id,
            "client_name": name,
            "redirect_uris": uris,
            "token_endpoint_auth_method": method,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": SCOPE,
        }
        if secret:
            out["client_secret"] = secret
        return out

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        row = _row(
            self.db.conn.execute(
                "SELECT * FROM mcp_oauth_clients WHERE client_id = ?",
                (client_id,),
            ).fetchone()
        )
        if row is None:
            return None
        row["redirect_uris"] = _load(row.pop("redirect_uris_json"), [])
        return row

    def client_secret_ok(self, client: dict[str, Any], secret: str | None) -> bool:
        if client["auth_method"] == "none":
            return True
        if not secret or not client.get("secret_hash"):
            return False
        return hmac.compare_digest(sha256_hex(secret), client["secret_hash"])

    def issue_code(
        self,
        *,
        client_id: str,
        account_id: str,
        user_id: str,
        redirect_uri: str,
        code_challenge: str,
        scope: str,
    ) -> str:
        code = CODE_PREFIX + secrets.token_urlsafe(32)
        now = utc_now()
        self.db.conn.execute(
            """
            INSERT INTO mcp_auth_codes (
                code_hash, client_id, account_id, user_id, redirect_uri, code_challenge,
                scope, expires_at, used_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                sha256_hex(code),
                client_id,
                account_id,
                user_id,
                redirect_uri,
                code_challenge,
                scope,
                _iso_after(CODE_TTL),
                now,
            ),
        )
        self.db.conn.commit()
        return code

    def exchange_code(
        self,
        *,
        code: str,
        client_id: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> dict[str, Any]:
        row = _row(
            self.db.conn.execute(
                "SELECT * FROM mcp_auth_codes WHERE code_hash = ?",
                (sha256_hex(code),),
            ).fetchone()
        )
        if row is None or row.get("used_at"):
            raise ValueError("invalid_grant")
        if row["client_id"] != client_id or row["redirect_uri"] != redirect_uri:
            raise ValueError("invalid_grant")
        if row["expires_at"] < utc_now():
            raise ValueError("invalid_grant")
        if not pkce_verifier_ok(code_verifier) or pkce_s256(code_verifier) != row["code_challenge"]:
            raise ValueError("invalid_grant")
        claimed = self.db.conn.execute(
            "UPDATE mcp_auth_codes SET used_at = ? WHERE code_hash = ? AND used_at IS NULL",
            (utc_now(), row["code_hash"]),
        )
        if claimed.rowcount != 1:
            self.db.conn.rollback()
            raise ValueError("invalid_grant")
        client = self.get_client(client_id)
        name = client["client_name"] if client else "AI client"
        try:
            issued = self._mint_grant(
                account_id=row["account_id"],
                user_id=row["user_id"],
                client_id=client_id,
                client_name=name,
                scope=row["scope"] or SCOPE,
                session_id=None,
                commit=False,
            )
        except Exception:
            self.db.conn.rollback()
            raise
        self.db.conn.commit()
        return issued

    def refresh(self, *, refresh_token: str, client_id: str) -> dict[str, Any]:
        digest = sha256_hex(refresh_token)
        row = self._grant_for_refresh(client_id, digest)
        if row is None or row["refresh_expires_at"] < utc_now():
            raise ValueError("invalid_grant")
        if not hmac.compare_digest(digest, row["refresh_hash"]):
            self.revoke_grant(row["account_id"], row["id"])
            raise ValueError("invalid_grant")
        try:
            return self._mint_grant(
                account_id=row["account_id"],
                user_id=row["user_id"],
                client_id=row["client_id"],
                client_name=row["client_name"],
                scope=row["scope"],
                session_id=row.get("session_id"),
                replace_id=row["id"],
                previous_refresh_hash=row["refresh_hash"],
                expected_refresh_hash=digest,
            )
        except ValueError as exc:
            if str(exc) != "refresh_conflict":
                raise
            again = self._grant_for_refresh(client_id, digest)
            if again is not None and not hmac.compare_digest(digest, again["refresh_hash"]):
                self.revoke_grant(again["account_id"], again["id"])
            raise ValueError("invalid_grant") from exc

    def _grant_for_refresh(self, client_id: str, digest: str) -> dict[str, Any] | None:
        return _row(
            self.db.conn.execute(
                """
                SELECT g.* FROM mcp_grants g
                WHERE g.client_id = ? AND g.revoked_at IS NULL AND (
                    g.refresh_hash = ? OR g.previous_refresh_hash = ?
                    OR EXISTS (
                        SELECT 1 FROM mcp_spent_refreshes s
                        WHERE s.grant_id = g.id AND s.refresh_hash = ?
                    )
                )
                """,
                (client_id, digest, digest, digest),
            ).fetchone()
        )

    def _mint_grant(
        self,
        *,
        account_id: str,
        user_id: str,
        client_id: str,
        client_name: str,
        scope: str,
        session_id: str | None,
        replace_id: str | None = None,
        previous_refresh_hash: str | None = None,
        expected_refresh_hash: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        access = ACCESS_PREFIX + secrets.token_urlsafe(32)
        refresh = REFRESH_PREFIX + secrets.token_urlsafe(32)
        now = utc_now()
        access_exp = _iso_after(ACCESS_TTL)
        refresh_exp = _iso_after(REFRESH_TTL)
        grant_id = replace_id or new_id("mgr_")
        if replace_id:
            rotated = self.db.conn.execute(
                """
                UPDATE mcp_grants
                SET access_hash = ?, refresh_hash = ?, previous_refresh_hash = ?,
                    access_expires_at = ?, refresh_expires_at = ?, last_used_at = ?
                WHERE id = ? AND account_id = ? AND revoked_at IS NULL AND refresh_hash = ?
                """,
                (
                    sha256_hex(access),
                    sha256_hex(refresh),
                    previous_refresh_hash,
                    access_exp,
                    refresh_exp,
                    now,
                    replace_id,
                    account_id,
                    expected_refresh_hash or previous_refresh_hash,
                ),
            )
            if rotated.rowcount != 1:
                self.db.conn.rollback()
                raise ValueError("refresh_conflict")
            if previous_refresh_hash:
                self.db.conn.execute(
                    """
                    INSERT INTO mcp_spent_refreshes (grant_id, refresh_hash, created_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT (grant_id, refresh_hash) DO NOTHING
                    """,
                    (replace_id, previous_refresh_hash, now),
                )
        else:
            self.db.conn.execute(
                """
                INSERT INTO mcp_grants (
                    id, account_id, user_id, client_id, client_name, access_hash, refresh_hash,
                    previous_refresh_hash, access_expires_at, refresh_expires_at, scope,
                    session_id, created_at, last_used_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    grant_id,
                    account_id,
                    user_id,
                    client_id,
                    client_name,
                    sha256_hex(access),
                    sha256_hex(refresh),
                    access_exp,
                    refresh_exp,
                    scope,
                    session_id,
                    now,
                    now,
                ),
            )
        if commit:
            self.db.conn.commit()
        return {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": int(ACCESS_TTL.total_seconds()),
            "refresh_token": refresh,
            "scope": scope,
            "grant_id": grant_id,
        }

    def grant_for_access(self, token: str) -> tuple[dict[str, Any] | None, str]:
        if not token or not token.startswith(ACCESS_PREFIX):
            return None, "invalid_token"
        row = _row(
            self.db.conn.execute(
                "SELECT * FROM mcp_grants WHERE access_hash = ?",
                (sha256_hex(token),),
            ).fetchone()
        )
        if row is None or row.get("revoked_at"):
            return None, "invalid_token"
        if row["access_expires_at"] < utc_now():
            return None, "invalid_token"
        now = utc_now()
        self.db.conn.execute(
            "UPDATE mcp_grants SET last_used_at = ? WHERE id = ?",
            (now, row["id"]),
        )
        self.db.conn.commit()
        row["last_used_at"] = now
        return row, ""

    def ensure_session(self, grant: dict[str, Any], *, label: str | None = None) -> dict[str, Any]:
        fresh = self._load_grant(str(grant["id"]))
        if fresh and fresh.get("session_id"):
            grant["session_id"] = fresh["session_id"]
        current = self.session_for_grant(grant)
        if current and current["status"] == "active":
            self.touch_session(current["id"])
            current["last_seen_at"] = utc_now()
            return current
        now = utc_now()
        if grant.get("session_id"):
            self.db.conn.execute(
                "UPDATE mcp_grants SET session_id = NULL WHERE id = ? AND session_id = ?",
                (grant["id"], grant["session_id"]),
            )
        session_id = new_id("ags_")
        name = (label or grant.get("client_name") or "agent").strip()[:120]
        self.db.conn.execute(
            """
            INSERT INTO agent_sessions (
                id, account_id, grant_id, label, lanes_json, capabilities_json, status,
                created_at, updated_at, last_seen_at
            ) VALUES (?, ?, ?, ?, '[]', ?, 'active', ?, ?, ?)
            """,
            (session_id, grant["account_id"], grant["id"], name, _dump(empty_capabilities()), now, now, now),
        )
        linked = self.db.conn.execute(
            """
            UPDATE mcp_grants SET session_id = ?
            WHERE id = ? AND revoked_at IS NULL AND session_id IS NULL
            """,
            (session_id, grant["id"]),
        )
        if linked.rowcount != 1:
            self.db.conn.rollback()
            won = self._load_grant(str(grant["id"]))
            if won and won.get("session_id"):
                grant["session_id"] = won["session_id"]
                existing = self.session_for_grant(grant)
                if existing and existing["status"] == "active":
                    self.touch_session(existing["id"])
                    return existing
            raise ValueError("session was not linked")
        self.db.conn.commit()
        grant["session_id"] = session_id
        stored = self.get_session(grant["account_id"], session_id)
        if stored is None:
            raise ValueError("session was not linked")
        return stored

    def _load_grant(self, grant_id: str) -> dict[str, Any] | None:
        return _row(
            self.db.conn.execute("SELECT * FROM mcp_grants WHERE id = ?", (grant_id,)).fetchone()
        )

    def touch_session(self, session_id: str) -> None:
        now = utc_now()
        self.db.conn.execute(
            "UPDATE agent_sessions SET last_seen_at = ?, updated_at = ? WHERE id = ?",
            (now, now, session_id),
        )
        self.db.conn.commit()

    def session_for_grant(self, grant: dict[str, Any]) -> dict[str, Any] | None:
        session_id = grant.get("session_id")
        if not session_id:
            return None
        return self.get_session(grant["account_id"], session_id)

    def get_session(self, account_id: str, session_id: str) -> dict[str, Any] | None:
        row = _row(
            self.db.conn.execute(
                "SELECT * FROM agent_sessions WHERE account_id = ? AND id = ?",
                (account_id, session_id),
            ).fetchone()
        )
        return _public_session(row) if row else None

    def set_lanes(self, account_id: str, session_id: str, lanes: list[str]) -> dict[str, Any]:
        canonical: list[str] = []
        for raw in lanes:
            lane = normalize_lane(str(raw))
            if lane is None:
                raise ValueError("lanes must be find, apply, and/or outreach")
            if lane not in canonical:
                canonical.append(lane)
        if not canonical:
            raise ValueError("pick at least one lane")
        now = utc_now()
        cur = self.db.conn.execute(
            """
            UPDATE agent_sessions
            SET lanes_json = ?, updated_at = ?, last_seen_at = ?
            WHERE account_id = ? AND id = ? AND status = 'active'
            """,
            (_dump(canonical), now, now, account_id, session_id),
        )
        self.db.conn.commit()
        if cur.rowcount == 0:
            raise ValueError("session is not active")
        session = self.get_session(account_id, session_id)
        if session is None:
            raise ValueError("session is not active")
        return session

    def set_capabilities(
        self,
        account_id: str,
        session_id: str,
        *,
        browser: bool,
        email: bool,
    ) -> dict[str, Any]:
        caps = normalize_capabilities({"browser": browser, "email": email}, reported=True)
        now = utc_now()
        cur = self.db.conn.execute(
            """
            UPDATE agent_sessions
            SET capabilities_json = ?, updated_at = ?, last_seen_at = ?
            WHERE account_id = ? AND id = ? AND status = 'active'
            """,
            (_dump(caps), now, now, account_id, session_id),
        )
        self.db.conn.commit()
        if cur.rowcount == 0:
            raise ValueError("session is not active")
        session = self.get_session(account_id, session_id)
        if session is None:
            raise ValueError("session is not active")
        return session

    def end_session(self, account_id: str, session_id: str) -> None:
        now = utc_now()
        self.db.conn.execute(
            """
            UPDATE agent_sessions SET status = 'ended', updated_at = ?
            WHERE account_id = ? AND id = ?
            """,
            (now, account_id, session_id),
        )
        self.db.conn.execute(
            """
            UPDATE agent_loops SET status = 'stopped', updated_at = ?
            WHERE account_id = ? AND session_id = ? AND status = 'running'
            """,
            (now, account_id, session_id),
        )
        self.db.conn.execute(
            "UPDATE mcp_grants SET session_id = NULL WHERE account_id = ? AND session_id = ?",
            (account_id, session_id),
        )
        self.db.conn.commit()

    def revoke_grant(self, account_id: str, grant_id: str) -> bool:
        row = _row(
            self.db.conn.execute(
                "SELECT * FROM mcp_grants WHERE account_id = ? AND id = ?",
                (account_id, grant_id),
            ).fetchone()
        )
        if row is None:
            return False
        now = utc_now()
        self.db.conn.execute(
            "UPDATE mcp_grants SET revoked_at = ? WHERE id = ? AND account_id = ?",
            (now, grant_id, account_id),
        )
        if row.get("session_id"):
            self.end_session(account_id, row["session_id"])
        else:
            self.db.conn.commit()
        return True

    def list_grants(self, account_id: str) -> list[dict[str, Any]]:
        cur = self.db.conn.execute(
            """
            SELECT * FROM mcp_grants
            WHERE account_id = ? AND revoked_at IS NULL
            ORDER BY created_at DESC
            """,
            (account_id,),
        )
        out = []
        for raw in cur.fetchall():
            row = dict(raw)
            session = self.get_session(account_id, row["session_id"]) if row.get("session_id") else None
            out.append(
                {
                    "id": row["id"],
                    "client_name": row["client_name"],
                    "created_at": row["created_at"],
                    "last_used_at": row.get("last_used_at"),
                    "access_expires_at": row["access_expires_at"],
                    "refresh_expires_at": row["refresh_expires_at"],
                    "scope": row["scope"],
                    "session": session,
                }
            )
        return out

    def record_use(self, account_id: str, session_id: str, *, kind: str, slug: str, note: str) -> dict[str, Any]:
        if kind not in {"skill", "mcp"}:
            raise ValueError("kind must be skill or mcp")
        slug_text = (slug or "").strip()[:80]
        if not slug_text:
            raise ValueError("slug is required")
        now = utc_now()
        use_id = new_id("use_")
        self.db.conn.execute(
            """
            INSERT INTO agent_uses (id, account_id, session_id, kind, slug, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (use_id, account_id, session_id, kind, slug_text, (note or "").strip()[:400] or None, now),
        )
        self.db.conn.commit()
        return {"id": use_id, "kind": kind, "slug": slug_text, "note": note, "created_at": now}

    def list_uses(self, account_id: str, *, session_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        if session_id:
            cur = self.db.conn.execute(
                """
                SELECT * FROM agent_uses
                WHERE account_id = ? AND session_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (account_id, session_id, limit),
            )
        else:
            cur = self.db.conn.execute(
                """
                SELECT * FROM agent_uses WHERE account_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (account_id, limit),
            )
        return [
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "kind": row["kind"],
                "slug": row["slug"],
                "note": row.get("note") or "",
                "created_at": row["created_at"],
            }
            for row in (dict(item) for item in cur.fetchall())
        ]

    def add_steer(
        self,
        account_id: str,
        *,
        author_user_id: str,
        body: str,
        session_id: str | None,
    ) -> dict[str, Any]:
        text = (body or "").strip()
        if len(text) < 8 or len(text) > 800:
            raise ValueError("steer must be 8–800 characters")
        if session_id and self.get_session(account_id, session_id) is None:
            raise ValueError("unknown session")
        now = utc_now()
        steer_id = new_id("steer_")
        self.db.conn.execute(
            """
            INSERT INTO agent_steers (id, account_id, session_id, author_user_id, body, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (steer_id, account_id, session_id or None, author_user_id, text, now),
        )
        self.db.conn.commit()
        return {
            "id": steer_id,
            "session_id": session_id,
            "body": text,
            "created_at": now,
        }

    def list_steers(self, account_id: str, *, session_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        if session_id:
            cur = self.db.conn.execute(
                """
                SELECT * FROM agent_steers
                WHERE account_id = ? AND (session_id IS NULL OR session_id = ?)
                ORDER BY created_at DESC LIMIT ?
                """,
                (account_id, session_id, limit),
            )
        else:
            cur = self.db.conn.execute(
                """
                SELECT * FROM agent_steers WHERE account_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (account_id, limit),
            )
        return [
            {
                "id": row["id"],
                "session_id": row.get("session_id"),
                "body": row["body"],
                "created_at": row["created_at"],
            }
            for row in (dict(item) for item in cur.fetchall())
        ]

    def start_loop(
        self,
        account_id: str,
        session_id: str,
        *,
        lane: str,
        goal: str,
    ) -> dict[str, Any]:
        canonical = normalize_lane(lane)
        if canonical is None:
            raise ValueError("lane must be find, apply, or outreach")
        now = utc_now()
        loop_id = new_id("loop_")
        self.db.conn.execute(
            """
            INSERT INTO agent_loops (
                id, account_id, session_id, lane, goal, status, step, cursor_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'running', 0, '{}', ?, ?)
            """,
            (loop_id, account_id, session_id, canonical, (goal or "").strip()[:240], now, now),
        )
        self.db.conn.commit()
        loop = self.get_loop(account_id, loop_id)
        if loop is None:
            raise ValueError("loop was not stored")
        return loop

    def get_loop(self, account_id: str, loop_id: str) -> dict[str, Any] | None:
        row = _row(
            self.db.conn.execute(
                "SELECT * FROM agent_loops WHERE account_id = ? AND id = ?",
                (account_id, loop_id),
            ).fetchone()
        )
        return _public_loop(row) if row else None

    def list_loops(self, account_id: str, session_id: str) -> list[dict[str, Any]]:
        cur = self.db.conn.execute(
            """
            SELECT * FROM agent_loops
            WHERE account_id = ? AND session_id = ?
            ORDER BY created_at DESC
            """,
            (account_id, session_id),
        )
        return [_public_loop(dict(row)) for row in cur.fetchall()]

    def active_loop(self, account_id: str, session_id: str, loop_id: str | None) -> dict[str, Any] | None:
        if loop_id:
            return self.get_loop(account_id, loop_id)
        cur = self.db.conn.execute(
            """
            SELECT * FROM agent_loops
            WHERE account_id = ? AND session_id = ? AND status = 'running'
            ORDER BY created_at DESC LIMIT 1
            """,
            (account_id, session_id),
        )
        row = cur.fetchone()
        return _public_loop(dict(row)) if row else None

    def save_loop(self, account_id: str, loop_id: str, *, status: str, step: int) -> dict[str, Any]:
        now = utc_now()
        self.db.conn.execute(
            """
            UPDATE agent_loops SET status = ?, step = ?, updated_at = ?
            WHERE account_id = ? AND id = ?
            """,
            (status, step, now, account_id, loop_id),
        )
        self.db.conn.commit()
        loop = self.get_loop(account_id, loop_id)
        if loop is None:
            raise ValueError("loop missing")
        return loop

    def tenant(self, account_id: str) -> TenantContext:
        return TenantContext(account_id)


def _public_session(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    caps = normalize_capabilities(_load(row.get("capabilities_json"), {}), reported=False)
    stored = _load(row.get("capabilities_json"), {})
    if isinstance(stored, dict) and "reported" in stored:
        caps["reported"] = bool(stored.get("reported"))
    return {
        "id": row["id"],
        "grant_id": row["grant_id"],
        "label": row["label"],
        "lanes": list(_load(row.get("lanes_json"), [])),
        "capabilities": caps,
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_seen_at": row["last_seen_at"],
    }


def _public_loop(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "lane": row["lane"],
        "goal": row.get("goal") or "",
        "status": row["status"],
        "step": int(row.get("step") or 0),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def plan_loop(loop: dict[str, Any], jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Next concrete step for a loop. The agent calls this again without a new human prompt."""
    lane = loop["lane"]
    open_jobs = [job for job in jobs if not job.get("stopped")]
    if lane == "find":
        shortlist = [job for job in open_jobs if job.get("status") in FIND_SHORTLIST]
        sources: list[str] = []
        for job in open_jobs:
            for source in job.get("sources") or []:
                if source and source not in sources:
                    sources.append(str(source))
        if len(shortlist) >= FIND_CAP:
            return {
                "status": "done",
                "continue": False,
                "lane": lane,
                "shortlist_count": len(shortlist),
                "shortlist_cap": FIND_CAP,
                "instruction": (
                    f"Shortlist is {len(shortlist)}, at the cap of {FIND_CAP}. "
                    "Stop this find loop. Tell the human the ids and scores. Do not Easy Apply."
                ),
            }
        return {
            "status": "running",
            "continue": True,
            "lane": lane,
            "shortlist_count": len(shortlist),
            "shortlist_cap": FIND_CAP,
            "sources_already_seen": sources[:40],
            "instruction": (
                "Search the next source you have not covered. Dedup, then create_job. "
                "Score and write an apply packet for anything you shortlist. "
                "Do not submit an application. When that source is done, call next_loop again."
            ),
        }
    if lane == "apply":
        pending = [job for job in open_jobs if job.get("status") in APPLY_OPEN]
        if not pending:
            return {
                "status": "blocked",
                "continue": False,
                "lane": lane,
                "instruction": (
                    "No apply_ready job. Tell the human. If find is also in this session, start_loop on find."
                ),
            }
        job = pending[0]
        return {
            "status": "running",
            "continue": True,
            "lane": lane,
            "job_id": job["id"],
            "company": job.get("company"),
            "title": job.get("title"),
            "instruction": (
                f"Open {job['id']} with get_job. Follow its apply packet in the browser. "
                "Then update_job with proof and status applied, and call next_loop."
            ),
        }
    pending = [job for job in open_jobs if job.get("status") == "outreach_ready"]
    if not pending:
        pending = [job for job in open_jobs if job.get("status") == "applied"]
    if not pending:
        return {
            "status": "blocked",
            "continue": False,
            "lane": lane,
            "instruction": "Nothing is ready for outreach. Tell the human. Do not invent a contact.",
        }
    job = pending[0]
    return {
        "status": "running",
        "continue": True,
        "lane": lane,
        "job_id": job["id"],
        "company": job.get("company"),
        "title": job.get("title"),
        "instruction": (
            f"Read the outreach skill. Email for {job['id']} with the resume PDF attached, "
            "or a short LinkedIn note that asks for a chat. No SMS. "
            "Record the touch with update_job, then call next_loop."
        ),
    }
