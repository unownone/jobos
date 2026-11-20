"""Pick Hub's Postgres URL from secrets, or the bundled Compose service.

Compose interpolates platform secrets (Coolify, Railway, repo-root ``.env``)
into ``DATABASE_URL_FROM_SECRET`` so an empty default does not wipe
``board/.env``. A loopback ``DATABASE_URL`` in ``board/.env`` is the bare-metal
example and is not used inside Compose.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote, urlparse

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_DEFAULT_SECRET_FILE = Path("/run/secrets/database_url")


def resolve_database_url(
    environ: Mapping[str, str] | None = None,
    *,
    secret_file: Path | None = None,
) -> str:
    env = dict(os.environ if environ is None else environ)
    platform = _clean(env.get("DATABASE_URL_FROM_SECRET"))
    if platform:
        return platform
    file_url = _read_secret_file(secret_file)
    if file_url:
        return file_url
    configured = _clean(env.get("DATABASE_URL"))
    if configured and not _is_loopback(configured):
        return configured
    return _bundled_url(env)


def _bundled_url(env: Mapping[str, str]) -> str:
    user = quote(_or_default(env, "JOBOS_PG_USER", "jobos"), safe="")
    password = quote(_or_default(env, "JOBOS_PG_PASSWORD", "jobos"), safe="")
    host = _or_default(env, "JOBOS_PG_HOST", "postgres")
    port = _or_default(env, "JOBOS_PG_PORT", "5432")
    database = quote(_or_default(env, "JOBOS_PG_DB", "jobos"), safe="")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def _read_secret_file(secret_file: Path | None) -> str:
    path = _DEFAULT_SECRET_FILE if secret_file is None else secret_file
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip().strip('"').strip("'")


def _is_loopback(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return host in _LOOPBACK_HOSTS


def _or_default(env: Mapping[str, str], key: str, default: str) -> str:
    value = _clean(env.get(key))
    return value or default


def _clean(value: str | None) -> str:
    return (value or "").strip().strip('"').strip("'")
