"""Unit tests for the candidate gate allowlist."""

from __future__ import annotations

from app.gates import path_is_open


def test_auth_join_is_open_like_join_preview() -> None:
    """POST /api/auth/join is how agents redeem; GET /api/join/ already skipped the gate."""
    assert path_is_open("/api/join/inv_example") is True
    assert path_is_open("/join/inv_example") is True
    assert path_is_open("/api/auth/join") is True
    assert path_is_open("/api/auth/join/") is True


def test_jobs_and_invites_stay_gated() -> None:
    assert path_is_open("/api/jobs") is False
    assert path_is_open("/api/invites") is False
    assert path_is_open("/api/auth/bootstrap") is True
