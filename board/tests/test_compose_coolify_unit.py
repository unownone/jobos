"""Coolify-safe Compose volumes (no FastAPI boot).

Coolify's helper runs validateShellSafePath on every volume *source* before
Docker interpolates the file. `${` (and other shell metacharacters) abort the
deploy. Bind mounts under `~` or `/artifacts/<id>` also reset on each Coolify
checkout, which wipes Postgres and RabbitMQ. Durable data must be named volumes.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    REPO / "docker-compose.yml",
    REPO / "docker-compose.plain.yml",
    REPO / "docker-compose.traefik.yml",
    REPO / "board/docker-compose.yml",
)

# Mirrors Coolify bootstrap/helpers/shared.php validateShellSafePath().
COOLIFY_FORBIDDEN = (
    "`",
    "$(",
    "${",
    "|",
    "&",
    ";",
    "\n",
    "\r",
    "\t",
    ">",
    "<",
)

NAMED_VOLUME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
DURABLE_TARGETS = {
    "/var/lib/postgresql/data",
    "/var/lib/rabbitmq",
    "/var/lib/jobos/blobs",
}
ROOT_COMPOSE = {
    "docker-compose.yml",
    "docker-compose.plain.yml",
    "docker-compose.traefik.yml",
}


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _compose_docs() -> Iterator[tuple[Path, dict]]:
    for path in COMPOSE_FILES:
        raw = path.read_text(encoding="utf-8")
        doc = yaml.safe_load(raw)
        assert isinstance(doc, dict), path
        yield path, doc


def _volume_source(entry: object) -> str:
    if isinstance(entry, str):
        # Windows drive letters are not used here. Named volumes have no slash.
        if entry.startswith("./") or entry.startswith("../") or entry.startswith("~/") or entry.startswith("~"):
            return entry.split(":")[0]
        if entry.startswith("/"):
            # /abs/path:/container[:mode]
            left, _sep, _rest = entry.partition(":")
            return left
        return entry.split(":")[0]
    if isinstance(entry, dict):
        source = entry.get("source")
        assert isinstance(source, str), entry
        return source
    raise AssertionError(f"unsupported volume entry: {entry!r}")


def _volume_target(entry: object) -> str | None:
    if isinstance(entry, str):
        if entry.startswith("./") or entry.startswith("../") or entry.startswith("~") or entry.startswith("/"):
            parts = entry.split(":")
            if len(parts) >= 2:
                return parts[1]
            return None
        parts = entry.split(":")
        return parts[1] if len(parts) >= 2 else None
    if isinstance(entry, dict):
        target = entry.get("target")
        return target if isinstance(target, str) else None
    return None


def _service_volumes(doc: dict) -> Iterator[tuple[str, object]]:
    services = doc.get("services") or {}
    assert isinstance(services, dict)
    for name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        for entry in svc.get("volumes") or []:
            yield name, entry


def test_compose_files_exist() -> None:
    missing = [str(p) for p in COMPOSE_FILES if not p.is_file()]
    assert missing == []


def test_volume_sources_pass_coolify_validate_shell_safe_path() -> None:
    failures: list[str] = []
    for path, doc in _compose_docs():
        for service, entry in _service_volumes(doc):
            source = _volume_source(entry)
            for needle in COOLIFY_FORBIDDEN:
                if needle in source:
                    failures.append(
                        f"{_rel(path)} {service}: source {source!r} contains {needle!r}"
                    )
    assert failures == []


def test_durable_data_uses_named_volumes() -> None:
    """Postgres, RabbitMQ, and blobs must survive Coolify's per-deploy checkout."""
    failures: list[str] = []
    for path, doc in _compose_docs():
        declared = set((doc.get("volumes") or {}).keys()) if isinstance(doc.get("volumes"), dict) else set()
        seen_targets: set[str] = set()
        for service, entry in _service_volumes(doc):
            target = _volume_target(entry)
            if target not in DURABLE_TARGETS:
                continue
            seen_targets.add(target)
            source = _volume_source(entry)
            if source.startswith(("/", ".", "~")):
                failures.append(
                    f"{_rel(path)} {service}: {target} is a bind mount ({source!r}); "
                    "use a named volume so Coolify redeploys keep Postgres/RabbitMQ/blobs"
                )
                continue
            if not NAMED_VOLUME.match(source):
                failures.append(f"{_rel(path)} {service}: {source!r} is not a named volume")
            if source not in declared:
                failures.append(
                    f"{_rel(path)}: named volume {source!r} missing from top-level volumes:"
                )
        if _rel(path) in ROOT_COMPOSE:
            missing = DURABLE_TARGETS - seen_targets
            if missing:
                failures.append(f"{_rel(path)}: missing durable mounts {sorted(missing)}")
        elif "/var/lib/postgresql/data" not in seen_targets:
            failures.append(f"{_rel(path)}: postgres data volume missing")
    assert failures == []


def test_hub_database_url_comes_from_secrets() -> None:
    """Bundled Postgres stays in the file. Hub must not hardcode over a secret URL."""
    failures: list[str] = []
    for path, doc in _compose_docs():
        services = doc.get("services") or {}
        hub = services.get("hub")
        if not isinstance(hub, dict):
            failures.append(f"{_rel(path)}: hub service missing")
            continue
        environment = hub.get("environment") or {}
        if not isinstance(environment, dict):
            failures.append(f"{_rel(path)}: hub environment is not a mapping")
            continue
        secret = environment.get("DATABASE_URL")
        if secret != "${DATABASE_URL:-}":
            failures.append(
                f"{_rel(path)}: DATABASE_URL must pass through the secret, got {secret!r}"
            )
        if "DATABASE_URL_FROM_SECRET" in environment:
            failures.append(f"{_rel(path)}: DATABASE_URL_FROM_SECRET is redundant")
        for key, default in (
            ("JOBOS_PG_USER", "jobos"),
            ("JOBOS_PG_PASSWORD", "jobos"),
            ("JOBOS_PG_HOST", "postgres"),
            ("JOBOS_PG_PORT", "5432"),
            ("JOBOS_PG_DB", "jobos"),
        ):
            expected = f"${{{key}:-{default}}}"
            if environment.get(key) != expected:
                failures.append(f"{_rel(path)}: {key}={environment.get(key)!r}, want {expected}")
        hosts = hub.get("extra_hosts") or []
        if "host.docker.internal:host-gateway" not in hosts:
            failures.append(f"{_rel(path)}: hub cannot reach a Postgres on the Docker host")
        postgres = services.get("postgres") if isinstance(services, dict) else None
        if isinstance(postgres, dict):
            pg_env = postgres.get("environment") or {}
            if isinstance(pg_env, dict) and pg_env.get("POSTGRES_USER") not in {None, "jobos"}:
                failures.append(
                    f"{_rel(path)}: bundled POSTGRES_USER must stay jobos for existing pgdata volumes"
                )
            if isinstance(pg_env, dict) and pg_env.get("POSTGRES_DB") not in {None, "jobos"}:
                failures.append(
                    f"{_rel(path)}: bundled POSTGRES_DB must stay jobos for existing pgdata volumes"
                )
    assert failures == []


def test_repo_relative_binds_are_coolify_safe() -> None:
    for path, doc in _compose_docs():
        for service, entry in _service_volumes(doc):
            source = _volume_source(entry)
            if not (source.startswith("./") or source.startswith("../")):
                continue
            for needle in COOLIFY_FORBIDDEN:
                assert needle not in source, f"{_rel(path)} {service}: {source!r}"
            assert not source.startswith("~")
