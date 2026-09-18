"""One-time admin bootstrap: mint jh_boot_* , hash in SQLite, consume once."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.db import BoardDB, utc_now
from app.passwords import PASSWORD_MIN_LEN, hash_password, verify_password
from app.settings import Settings, parse_env_file
from app.tenant import AccountStore, TenantContext
from app.urls import resolve_public_url

BOOTSTRAP_PREFIX = "jh_boot_"
BOOTSTRAP_META_KEY = "bootstrap"
BOOTSTRAP_PLAIN_KEY = "bootstrap.token"
BOOTSTRAP_TTL = timedelta(days=7)
SESSION_IDLE = timedelta(hours=12)
TOKEN_ENV_KEY = "HUB_BOOTSTRAP_TOKEN"
USED_ENV_KEY = "HUB_BOOTSTRAP_USED"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_bootstrap_token() -> str:
    return BOOTSTRAP_PREFIX + secrets.token_urlsafe(32)


def new_id(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(16).replace("-", "").replace("_", "")[:26]


def public_base(settings: Settings) -> str:
    if settings.public_url:
        return resolve_public_url(public_url=settings.public_url)
    return resolve_public_url(listen_host=settings.host, listen_port=settings.port)


def format_signup_url(settings: Settings, token: str) -> str:
    return f"{public_base(settings)}/admin/signup#bootstrap={token}"


def format_signup_line(settings: Settings, token: str) -> str:
    return f"Admin signup: {format_signup_url(settings, token)}"


def env_path_for(settings: Settings) -> Path:
    return settings.env_path or (settings.board_dir / ".env")


def tokens_json_path_for(settings: Settings) -> Path:
    return settings.tokens_json_path or (settings.board_dir / "tokens.local.json")


def upsert_env_file(path: Path, updates: dict[str, str | None]) -> None:
    existing: dict[str, str] = {}
    prefix_lines: list[str] = []
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                if not existing:
                    prefix_lines.append(raw)
                continue
            key, value = stripped.split("=", 1)
            existing[key.strip()] = value.strip().strip('"').strip("'")
    for key, value in updates.items():
        if value is None:
            existing.pop(key, None)
        else:
            existing[key] = value
    lines = prefix_lines or ["# Generated locally — DO NOT COMMIT"]
    if lines and lines[-1] != "":
        pass
    ordered_keys = [
        "BOARD_HOST",
        "BOARD_PORT",
        "BOARD_DB",
        "BOARD_TOKEN_DISCOVERY",
        "BOARD_TOKEN_APPLY",
        "BOARD_TOKEN_OUTREACH",
        "BOARD_TOKEN_ADMIN",
        "BOARD_TOKEN_MAINTENANCE",
        "HUB_PUBLIC_HOST",
        "HUB_PUBLIC_URL",
        TOKEN_ENV_KEY,
        USED_ENV_KEY,
    ]
    seen: set[str] = set()
    body: list[str] = []
    for key in ordered_keys:
        if key in existing:
            body.append(f"{key}={existing[key]}")
            seen.add(key)
    for key, value in existing.items():
        if key not in seen:
            body.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [line for line in lines if line.startswith("#") or line == ""]
    if not header:
        header = ["# Generated locally — DO NOT COMMIT"]
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


def upsert_tokens_json(path: Path, *, bootstrap: str | None, remove_bootstrap: bool = False) -> None:
    payload: dict[str, Any] = {}
    if path.is_file():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            payload = raw
    if remove_bootstrap:
        payload.pop("bootstrap", None)
    elif bootstrap is not None:
        payload["bootstrap"] = bootstrap
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def wipe_bootstrap_plaintext(settings: Settings, db: BoardDB | None = None) -> None:
    env_file = env_path_for(settings)
    if env_file.is_file():
        upsert_env_file(
            env_file,
            {
                TOKEN_ENV_KEY: None,
                USED_ENV_KEY: "1",
            },
        )
    json_file = tokens_json_path_for(settings)
    if json_file.is_file():
        upsert_tokens_json(json_file, bootstrap=None, remove_bootstrap=True)
    if db is not None:
        db.delete_kv(BOOTSTRAP_PLAIN_KEY)


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _token_expired(created_at: str | None) -> bool:
    created = _parse_ts(created_at)
    if created is None:
        return False
    return datetime.now(timezone.utc) - created > BOOTSTRAP_TTL


def ensure_bootstrap(settings: Settings, db: BoardDB) -> str | None:
    """Mint or reuse unused bootstrap token. Returns plaintext if still unused."""
    if db.admin_bootstrapped():
        wipe_bootstrap_plaintext(settings, db)
        return None

    meta = db.get_secret_meta(BOOTSTRAP_META_KEY)
    env_token = (settings.bootstrap_token or "").strip()
    if not env_token:
        env_file = env_path_for(settings)
        if env_file.is_file():
            env_token = parse_env_file(env_file).get(TOKEN_ENV_KEY, "").strip()
    if not env_token:
        env_token = (db.get_kv(BOOTSTRAP_PLAIN_KEY) or "").strip()

    if meta and meta.get("used_at"):
        db.delete_kv(BOOTSTRAP_PLAIN_KEY)
        return None

    if meta and not _token_expired(str(meta.get("created_at") or "")):
        stored_hash = str(meta.get("value_hash") or "")
        if env_token and sha256_hex(env_token) == stored_hash:
            _persist_plaintext(settings, env_token, db)
            return env_token
        if env_token and sha256_hex(env_token) != stored_hash:
            db.upsert_secret_meta(BOOTSTRAP_META_KEY, sha256_hex(env_token))
            _persist_plaintext(settings, env_token, db)
            return env_token
        return env_token or None

    token = env_token if env_token else new_bootstrap_token()
    if token and not token.startswith(BOOTSTRAP_PREFIX):
        token = BOOTSTRAP_PREFIX + token
    db.upsert_secret_meta(BOOTSTRAP_META_KEY, sha256_hex(token))
    _persist_plaintext(settings, token, db)
    return token


def _persist_plaintext(settings: Settings, token: str, db: BoardDB | None = None) -> None:
    env_file = env_path_for(settings)
    extras: dict[str, str | None] = {TOKEN_ENV_KEY: token, USED_ENV_KEY: None}
    if settings.public_url:
        extras["HUB_PUBLIC_URL"] = settings.public_url
    if settings.host:
        extras.setdefault("BOARD_HOST", settings.host)
    extras.setdefault("BOARD_PORT", str(settings.port))
    upsert_env_file(env_file, extras)
    upsert_tokens_json(tokens_json_path_for(settings), bootstrap=token)
    if db is not None:
        db.put_kv(BOOTSTRAP_PLAIN_KEY, token)


def validate_signup(email: str, password: str) -> str | None:
    cleaned = email.strip().lower()
    if not _EMAIL_RE.match(cleaned):
        return "invalid email"
    if len(password) < PASSWORD_MIN_LEN:
        return f"password must be at least {PASSWORD_MIN_LEN} characters"
    return None


def token_matches(meta: dict[str, Any] | None, token: str) -> bool:
    if not meta or not token:
        return False
    if meta.get("used_at"):
        return False
    if _token_expired(str(meta.get("created_at") or "")):
        return False
    expected = str(meta.get("value_hash") or "")
    if not expected:
        return False
    return secrets.compare_digest(expected, sha256_hex(token))


def consume_bootstrap(
    settings: Settings,
    db: BoardDB,
    *,
    token: str,
    email: str,
    password: str,
) -> dict[str, Any]:
    """Create the first admin and disable the bootstrap token. Raises ValueError on failure."""
    err = validate_signup(email, password)
    if err:
        raise ValueError(err)
    meta = db.get_secret_meta(BOOTSTRAP_META_KEY)
    if db.admin_bootstrapped():
        raise PermissionError("signup closed; log in at /login")
    if not token_matches(meta, token):
        raise PermissionError("invalid or used bootstrap token")
    username = email.strip().lower().split("@", 1)[0]
    username = "".join(ch if ch.isalnum() or ch in "._-" else "" for ch in username)
    if len(username) < 3:
        username = "admin" + new_id("")[:8]
    store = AccountStore(db.conn)
    if store.get_by_username(username):
        username = username[:20] + new_id("")[:8]
    account_id = new_id("acc_")
    account = store.create(
        account_id=account_id,
        username=username,
        password_hash=hash_password(password),
        created_at=utc_now(),
    )
    user = db.create_admin(
        user_id=new_id("usr_"),
        email=email.strip().lower(),
        password_hash=hash_password(password),
        display_name="admin",
        account_id=account_id,
    )
    db.mark_secret_used(BOOTSTRAP_META_KEY)
    wipe_bootstrap_plaintext(settings, db)
    session_plain = secrets.token_urlsafe(32)
    csrf_plain = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + SESSION_IDLE
    db.create_session(
        session_id=new_id("ses_"),
        user_id=user["id"],
        token_hash=sha256_hex(session_plain),
        expires_at=expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        csrf_hash=sha256_hex(csrf_plain),
    )
    db.add_event(
        TenantContext(account_id),
        job_id=None,
        actor_role="admin",
        actor=user["email"],
        action="bootstrap",
        note="admin user created; bootstrap token consumed",
        fields={"user_id": user["id"], "account_id": account_id},
    )
    return {
        "user": user,
        "session_token": session_plain,
        "csrf_token": csrf_plain,
        "now": utc_now(),
        "account_id": account_id,
        "account": account,
    }
