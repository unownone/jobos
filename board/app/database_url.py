"""Pick Hub's Postgres URL from DATABASE_URL, or the bundled Compose service.

Compose passes the secret through as ``DATABASE_URL``. An empty value means
the bundled ``postgres`` service. A mounted Docker secret at
``/run/secrets/database_url`` is used only when ``DATABASE_URL`` is empty.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote

_DEFAULT_SECRET_FILE = Path("/run/secrets/database_url")


def resolve_database_url(
    environ: Mapping[str, str] | None = None,
    *,
    secret_file: Path | None = None,
) -> str:
    env = dict(os.environ if environ is None else environ)
    configured = _clean(env.get("DATABASE_URL"))
    if configured:
        return configured
    file_url = _read_secret_file(secret_file)
    if file_url:
        return file_url
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


def _or_default(env: Mapping[str, str], key: str, default: str) -> str:
    value = _clean(env.get(key))
    return value or default


def _clean(value: str | None) -> str:
    return (value or "").strip().strip('"').strip("'")
