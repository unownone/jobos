"""DATABASE_URL resolution: the secret when set, bundled Compose Postgres otherwise."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.database_url import resolve_database_url

pytestmark = pytest.mark.unit

BUNDLED = "postgresql://jobos:jobos@postgres:5432/jobos"


def test_unset_uses_bundled_compose_service() -> None:
    assert resolve_database_url({}) == BUNDLED


def test_database_url_secret_is_used_as_given() -> None:
    url = "postgresql://app:s3cret@db.internal:5432/jobos?sslmode=require"
    assert (
        resolve_database_url(
            {
                "DATABASE_URL": f"  {url}  ",
                "JOBOS_PG_HOST": "postgres",
            }
        )
        == url
    )


def test_explicit_loopback_url_is_kept() -> None:
    url = "postgresql://jobos:jobos@127.0.0.1:5432/jobos"
    assert resolve_database_url({"DATABASE_URL": url}) == url


def test_password_keeps_a_trailing_apostrophe() -> None:
    assert (
        resolve_database_url({"JOBOS_PG_PASSWORD": "secret'"})
        == "postgresql://jobos:secret%27@postgres:5432/jobos"
    )


def test_parts_build_outside_host_and_encode_password() -> None:
    assert (
        resolve_database_url(
            {
                "JOBOS_PG_USER": "app",
                "JOBOS_PG_PASSWORD": "p@ss:word",
                "JOBOS_PG_HOST": "host.docker.internal",
                "JOBOS_PG_PORT": "5433",
                "JOBOS_PG_DB": "jobos",
            }
        )
        == "postgresql://app:p%40ss%3Aword@host.docker.internal:5433/jobos"
    )


def test_docker_secret_file_when_database_url_is_unset(tmp_path: Path) -> None:
    secret = tmp_path / "database_url"
    secret.write_text("postgresql://u:p@secret-host:5432/jobos\n", encoding="utf-8")
    assert (
        resolve_database_url({}, secret_file=secret)
        == "postgresql://u:p@secret-host:5432/jobos"
    )


def test_database_url_wins_over_secret_file(tmp_path: Path) -> None:
    secret = tmp_path / "database_url"
    secret.write_text("postgresql://u:p@secret-host:5432/jobos\n", encoding="utf-8")
    url = "postgresql://app:s3cret@db.internal:5432/jobos"
    assert resolve_database_url({"DATABASE_URL": url}, secret_file=secret) == url


def test_missing_secret_file_is_ignored(tmp_path: Path) -> None:
    assert resolve_database_url({}, secret_file=tmp_path / "missing") == BUNDLED
