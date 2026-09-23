"""Rejected status enum + rejection object (no FastAPI boot)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.constants import PIPELINE_OPEN_STATUSES, REJECTION_BY, SHARED_STATUSES, STATUSES
from app.permissions import merge_rejection

SCHEMA = Path(__file__).resolve().parents[2] / "ledger" / "schema" / "job.schema.json"


def test_rejected_is_shared_closed_status() -> None:
    assert "rejected" in STATUSES
    assert SHARED_STATUSES == frozenset({"rejected"})
    assert "rejected" not in PIPELINE_OPEN_STATUSES
    assert REJECTION_BY == ("company", "user")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert "rejected" in schema["properties"]["status"]["enum"]
    assert "rejection" in schema["properties"]


def test_merge_rejection_remarks_shorthand() -> None:
    merged = merge_rejection(None, {"by": "company", "remarks": "filled internally"})
    assert merged["by"] == "company"
    assert merged["company_remarks"] == "filled internally"
    assert merged["user_remarks"] == ""
    both = merge_rejection(
        merged,
        {"by": "user", "user_remarks": "comp too low", "company_remarks": "filled internally"},
    )
    assert both["by"] == "user"
    assert both["user_remarks"] == "comp too low"
    assert both["company_remarks"] == "filled internally"


def test_merge_rejection_rejects_unknown_by() -> None:
    with pytest.raises(HTTPException) as exc:
        merge_rejection(None, {"by": "recruiter"})
    assert exc.value.status_code == 422


def test_merge_rejection_remarks_need_by() -> None:
    with pytest.raises(HTTPException) as exc:
        merge_rejection(None, {"remarks": "nope"})
    assert exc.value.status_code == 422
