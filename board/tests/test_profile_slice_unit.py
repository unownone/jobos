"""Candidate Profile public slice is YAML, not regex."""

from __future__ import annotations

from app.profile import public_slice_from_mapping, public_slice_from_text


def test_block_and_flow_lists_and_no_pii() -> None:
    text = """
identity:
  full_name: "Secret Person"
  phone: "555-0100"
  email: "hidden@example.test"
  work_authorization: "US citizen"
target:
  titles: ["Staff Engineer", "Principal"]
  locations:
    - Remote
  deal_breakers: ["Crypto"]
"""
    slice_ = public_slice_from_text(text)
    assert slice_["present"] is True
    assert slice_["target"]["titles"] == ["Staff Engineer", "Principal"]
    assert slice_["target"]["locations"] == ["Remote"]
    assert slice_["target"]["deal_breakers"] == ["Crypto"]
    assert slice_["work_authorization"] == "US citizen"
    dumped = str(slice_)
    assert "555-0100" not in dumped
    assert "hidden@example.test" not in dumped
    assert "Secret Person" not in dumped


def test_mapping_helper_matches_text() -> None:
    data = {
        "identity": {"work_authorization": "Authorized"},
        "target": {"titles": ["X"], "locations": [], "deal_breakers": None},
    }
    slice_ = public_slice_from_mapping(data)
    assert slice_["target"]["titles"] == ["X"]
    assert slice_["target"]["deal_breakers"] == []
    assert slice_["work_authorization"] == "Authorized"
