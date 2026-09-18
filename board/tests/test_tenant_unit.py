"""Account Module unit tests (no Hub app)."""

from __future__ import annotations

import pytest

from app.tenant import AccountError, TenantContext, validate_password, validate_username


def test_tenant_context_requires_account_id() -> None:
    with pytest.raises(ValueError):
        TenantContext("")
    assert TenantContext("acc_x").account_id == "acc_x"


def test_validate_username_rejects_reserved() -> None:
    with pytest.raises(AccountError) as exc:
        validate_username("admin")
    assert exc.value.status_code == 422


def test_validate_password_min_len() -> None:
    with pytest.raises(AccountError):
        validate_password("short")
    validate_password("long-enough")
