"""DATABASE_URL resolution: secrets first, bundled Compose Postgres otherwise."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.database_url import resolve_database_url

pytestmark = pytest.mark.unit

BUNDLED = "postgresql://jobos:jobos@postgres:5432/jobos"


def test_unset_uses_bundled_compose_service() -> None:
    assert resolve_database_url({}) == BUNDLED


def test_platform_secret_wins_over_board_env_and_parts() -> None:
    url = "postgresql://app:s3cret@db.internal:5432/jobos?sslmode=require"
    assert (
        resolve_database_url(
            {
                "DATABASE_URL_FROM_SECRET": url,
                "DATABASE_URL": "postgresql://other:x@elsewhere:5432/jobos",
                "JOBOS_PG_HOST": "postgres",
            }
        )
        == url
    )


def test_platform_secret_may_be_loopback_when_explicit() -> None:
    url = "postgresql://jobos:jobos@127.0.0.1:5432/jobos"
    assert resolve_database_url({"DATABASE_URL_FROM_SECRET": f"  {url}  "}) == url


def test_board_env_loopback_does_not_replace_bundled_service() -> None:
    for url in (
        "postgresql://jobos:jobos@127.0.0.1:5432/jobos",
        "postgresql://jobos:jobos@localhost:5432/jobos",
        "postgresql://jobos:jobos@[::1]:5432/jobos",
    ):
        assert resolve_database_url({"DATABASE_URL": url}) == BUNDLED


def test_board_env_outside_host_is_used() -> None:
    url = "postgresql://jobos:secret@db.example:5432/jobos?sslmode=require"
    assert resolve_database_url({"DATABASE_URL": url}) == url


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


def test_docker_secret_file_when_platform_url_is_unset(tmp_path: Path) -> None:
    secret = tmp_path / "database_url"
    secret.write_text("postgresql://u:p@secret-host:5432/jobos\n", encoding="utf-8")
    assert (
        resolve_database_url(
            {"DATABASE_URL": "postgresql://jobos:jobos@127.0.0.1:5432/jobos"},
            secret_file=secret,
        )
        == "postgresql://u:p@secret-host:5432/jobos"
    )


def test_missing_secret_file_is_ignored(tmp_path: Path) -> None:
    assert resolve_database_url({}, secret_file=tmp_path / "missing") == BUNDLED
