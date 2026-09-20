"""Unit tests for memory write gates. No FastAPI."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.memory_policy import (
    MemoryDenied,
    MemoryInvalid,
    content_hash,
    fts_match_query,
    resolve_read_pod,
    resolve_write_pod,
    validate_kind,
    validate_write_text,
    visible_pod_ids,
    worker_pod_id,
)


def _principal(**kwargs):
    data = {
        "role": "discovery",
        "actor": "disc-1",
        "user_id": "usr_disc1",
        "track": "discovery",
        "kind": "agent",
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def test_inspector_default_visibility_includes_all_tracks() -> None:
    admin = _principal(role="admin", kind="admin", track=None, user_id="usr_admin")
    pods = visible_pod_ids(admin)
    assert "common" in pods
    assert "track:discovery" in pods
    assert "track:outreach" in pods
    worker = _principal()
    assert "track:outreach" not in visible_pod_ids(worker)


def test_applicator_alias_writes_application_track() -> None:
    p = _principal(role="apply", track="application", user_id="usr_app1")
    assert resolve_write_pod(p, "applicator") == "track:application"
    assert resolve_write_pod(p, "apply") == "track:application"


def test_cannot_write_other_track_pod() -> None:
    p = _principal()
    with pytest.raises(MemoryDenied):
        resolve_write_pod(p, "track:application")


def test_cannot_read_other_worker_pod() -> None:
    p = _principal()
    with pytest.raises(MemoryDenied):
        resolve_read_pod(p, "worker:usr_other")


def test_mixed_case_worker_pod_id_is_own() -> None:
    p = _principal(user_id="usr_AbC123")
    assert resolve_write_pod(p, "worker:usr_AbC123") == "worker:usr_AbC123"
    assert worker_pod_id(p) == "worker:usr_AbC123"


def test_inspector_can_read_other_track() -> None:
    admin = _principal(role="admin", kind="admin", track=None, user_id="usr_admin")
    assert resolve_read_pod(admin, "track:discovery") == "track:discovery"


def test_rejects_secret_and_json_dump() -> None:
    with pytest.raises(MemoryInvalid):
        validate_write_text(
            kind="fact",
            scope="worker",
            title="Saved API key for later",
            body="The bearer jh_agt_not-a-real-key must never be stored in memory pods.",
        )
    ok_title, ok_body = validate_write_text(
        kind="portal_quirk",
        scope="track",
        title="Greenhouse work-auth radio",
        body=(
            "Acme Greenhouse asks a work-authorization radio that is missing from the "
            "apply packet. Bounce to discovery instead of guessing the legal answer."
        ),
    )
    assert "work-authorization" in ok_body
    with pytest.raises(MemoryInvalid):
        validate_write_text(
            kind="portal_quirk",
            scope="track",
            title="Raw payload from Greenhouse",
            body='{"job": "dump", "html": "<html>too much</html>"} extra words to pass length',
        )


def test_short_body_rejected() -> None:
    with pytest.raises(MemoryInvalid):
        validate_write_text(
            kind="portal_quirk",
            scope="track",
            title="Too short note",
            body="Nope.",
        )


def test_kind_not_allowed_on_common() -> None:
    with pytest.raises(MemoryInvalid):
        validate_kind("common", "portal_quirk")
    assert validate_kind("track", "portal_quirk") == "portal_quirk"


def test_content_hash_is_stable() -> None:
    a = content_hash(kind="fact", title="Hello There", body="Body text", company="Acme", job_id=None)
    b = content_hash(kind="fact", title="hello  there", body="Body  text", company="acme", job_id=None)
    assert a == b


def test_compat_worker_id_uses_actor() -> None:
    p = _principal(user_id=None, actor="Grok Discovery")
    assert worker_pod_id(p).startswith("worker:compat:discovery:")


def test_fts_query_quotes_tokens() -> None:
    assert fts_match_query("Greenhouse work-auth") == '"Greenhouse" AND "work" AND "auth"'
    assert fts_match_query("???") is None
