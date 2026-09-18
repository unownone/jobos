"""Tenant identity Module: accounts, authentication, TenantContext.

Depth lives here: callers pass a TenantContext; this Module creates accounts,
hashes passwords, seeds tracks, and never lets a principal exist without an
account_id. Isolation is an invariant of the Interface, not a handler branch.

Alternatives considered (see docs/job-hub/multi-tenant.md):
1. TenantContext as a required argument on every store method (chosen).
2. Per-request store objects with tenant baked in (more object churn).
3. Postgres RLS only (hides the Interface from tests).
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from typing import Any

from datetime import datetime, timezone

from app.constants import TRACKS
from app.passwords import PASSWORD_MIN_LEN, hash_password, new_id, verify_password


class AccountError(Exception):
    """Account Interface errors. The web Adapter maps status_code to HTTP."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{2,39}$")
RESERVED_USERNAMES = frozenset(
    {"admin", "root", "system", "compat", "__compat__", "jobos", "hub"}
)
COMPAT_ACCOUNT_ID = "acc_compat"
COMPAT_USERNAME = "__compat__"
ACCOUNT_ID_PREFIX = "acc_"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class TenantContext:
    """Required on every production data path. Empty account_id is a bug."""

    account_id: str

    def __post_init__(self) -> None:
        aid = (self.account_id or "").strip()
        if not aid:
            raise ValueError("TenantContext.account_id is required")
        object.__setattr__(self, "account_id", aid)

    @property
    def routing_key_prefix(self) -> str:
        return self.account_id


def account_id_of(obj: Any, default: str = COMPAT_ACCOUNT_ID) -> str:
    """Resolve account_id from a Principal, TenantContext, or mapping."""
    if obj is None:
        return default
    if isinstance(obj, TenantContext):
        return obj.account_id
    aid = getattr(obj, "account_id", None)
    if aid:
        return str(aid)
    tenant = getattr(obj, "tenant", None)
    if tenant is not None:
        return str(getattr(tenant, "account_id", "") or default)
    if isinstance(obj, dict) and obj.get("account_id"):
        return str(obj["account_id"])
    return default


def require_tenant(principal: Any) -> TenantContext:
    account_id = str(getattr(principal, "account_id", None) or "").strip()
    if not account_id:
        raise AccountError(401, "tenant required")
    return TenantContext(account_id)


def validate_username(username: str) -> str:
    cleaned = (username or "").strip()
    if not USERNAME_RE.match(cleaned):
        raise AccountError(
            422,
            "username must be 3–40 chars, start with a letter, and use letters, digits, _ . -",
        )
    if cleaned.lower() in RESERVED_USERNAMES:
        raise AccountError(422, "username is reserved")
    return cleaned


def validate_password(password: str) -> None:
    if len(password or "") < PASSWORD_MIN_LEN:
        raise AccountError(422, f"password must be at least {PASSWORD_MIN_LEN} characters")


class AccountStore:
    """Persistence for the accounts table. Callers never write SQL for tenancy."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def get(self, account_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        row = cur.fetchone()
        return _row_to_account(row) if row else None

    def get_by_username(self, username: str) -> dict[str, Any] | None:
        cur = self.conn.execute(
            "SELECT * FROM accounts WHERE lower(username) = lower(?)",
            (username.strip(),),
        )
        row = cur.fetchone()
        return _row_to_account(row) if row else None

    def create(
        self,
        *,
        account_id: str,
        username: str,
        password_hash: str,
        created_at: str,
        tracks: list[str] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        self.conn.execute(
            """
            INSERT INTO accounts (id, username, password_hash, created_at, tracks_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                account_id,
                username,
                password_hash,
                created_at,
                json.dumps(list(tracks or TRACKS), ensure_ascii=False),
            ),
        )
        if commit:
            self.conn.commit()
        stored = self.get(account_id)
        if stored is None:
            raise RuntimeError("account insert did not persist")
        return stored

    def ensure_compat(self, *, now: str) -> TenantContext:
        existing = self.get(COMPAT_ACCOUNT_ID)
        if existing is None:
            self.create(
                account_id=COMPAT_ACCOUNT_ID,
                username=COMPAT_USERNAME,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                created_at=now,
                tracks=list(TRACKS),
            )
        return TenantContext(COMPAT_ACCOUNT_ID)


class AccountService:
    """Deep account Interface: signup, login, resolve. Password KDF stays inside."""

    def __init__(self, db: Any) -> None:
        self.db = db
        self.store = AccountStore(db.conn)

    def signup(self, username: str, password: str) -> dict[str, Any]:
        name = validate_username(username)
        validate_password(password)
        if self.store.get_by_username(name):
            raise AccountError(409, "username already taken")
        now = utc_stamp()
        account_id = new_id(ACCOUNT_ID_PREFIX)
        password_hash = hash_password(password)
        self.db.begin_immediate()
        try:
            if self.store.get_by_username(name):
                self.db.rollback()
                raise AccountError(409, "username already taken")
            account = self.store.create(
                account_id=account_id,
                username=name,
                password_hash=password_hash,
                created_at=now,
                commit=False,
            )
            user = self.db.insert_user(
                user_id=new_id("usr_"),
                kind="admin",
                track=None,
                email=None,
                password_hash=password_hash,
                display_name=name,
                metadata={"username": name},
                created_by=None,
                account_id=account_id,
                commit=False,
            )
            self.db.conn.commit()
        except AccountError:
            self.db.rollback()
            raise
        except Exception:
            self.db.rollback()
            raise
        return {
            "account": public_account(account),
            "user": user,
            "tenant": TenantContext(account_id),
        }

    def login(self, username: str, password: str, *, email: str | None = None) -> dict[str, Any]:
        account = None
        user = None
        ident = (username or "").strip()
        if ident:
            account = self.store.get_by_username(ident)
            if account and verify_password(account["password_hash"], password):
                user = self.db.admin_for_account(account["id"])
        if user is None and (email or ident):
            lookup = (email or ident).strip()
            user = self.db.get_user_by_email(lookup)
            if user is None or not user.get("password_hash"):
                raise AccountError(401, "invalid username or password")
            if not verify_password(user["password_hash"], password):
                raise AccountError(401, "invalid username or password")
            account_id = user.get("account_id") or COMPAT_ACCOUNT_ID
            account = self.store.get(account_id)
        if user is None or not account:
            raise AccountError(401, "invalid username or password")
        if user.get("disabled_at"):
            raise AccountError(401, "user disabled")
        return {
            "account": public_account(account),
            "user": user,
            "tenant": TenantContext(account["id"]),
        }

    def tenant_for_user(self, user: dict[str, Any]) -> TenantContext:
        account_id = str(user.get("account_id") or "").strip()
        if not account_id:
            return self.store.ensure_compat(now=utc_stamp())
        return TenantContext(account_id)


def public_account(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "tracks": list(row.get("tracks") or TRACKS),
        "created_at": row["created_at"],
    }


def _row_to_account(row: Any) -> dict[str, Any]:
    tracks_raw = row["tracks_json"] if "tracks_json" in row.keys() else None
    if tracks_raw:
        tracks = json.loads(tracks_raw)
    else:
        tracks = list(TRACKS)
    return {
        "id": row["id"],
        "username": row["username"],
        "password_hash": row["password_hash"],
        "created_at": row["created_at"],
        "tracks": tracks,
    }
