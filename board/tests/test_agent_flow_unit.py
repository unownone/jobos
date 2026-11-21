"""Lane checks and loop planning for the agent session. No HTTP."""

from __future__ import annotations

from app.agent_flow import evaluate_lane, pkce_verifier_ok, plan_loop, redirect_uri_allowed
from app.mcp_http import _with_query


def _session(lanes: list[str], *, browser: bool = False, email: bool = False, reported: bool = False) -> dict:
    return {
        "lanes": lanes,
        "capabilities": {"browser": browser, "email": email, "reported": reported},
    }


def test_find_blocks_until_the_human_picks_lanes_and_a_browser_exists() -> None:
    unset = evaluate_lane(_session([]), "find")
    assert unset["can"] is False
    assert unset["reason"] == "lanes_unset"
    assert "Ask the human" in unset["instruction"]

    unreported = evaluate_lane(_session(["find", "apply"]), "find")
    assert unreported["can"] is False
    assert unreported["reason"] == "capabilities_not_reported"

    no_browser = evaluate_lane(_session(["find"], browser=False, email=True, reported=True), "find")
    assert no_browser["can"] is False
    assert "browser" in no_browser["missing"]

    ready = evaluate_lane(_session(["find", "outreach"], browser=True, email=False, reported=True), "find")
    assert ready["can"] is True
    assert ready["skill"] == "job-discovery"


def test_outreach_needs_email_and_apply_needs_browser() -> None:
    caps = _session(["apply", "outreach"], browser=True, email=False, reported=True)
    assert evaluate_lane(caps, "apply")["can"] is True
    outreach = evaluate_lane(caps, "outreach")
    assert outreach["can"] is False
    assert outreach["missing"] == ["email"]

    outside = evaluate_lane(_session(["find"], browser=True, email=True, reported=True), "apply")
    assert outside["reason"] == "lane_not_in_session"


def test_find_loop_stops_at_the_shortlist_cap() -> None:
    jobs = [
        {"id": f"board__{i}", "status": "apply_ready", "stopped": False, "sources": ["indeed"], "company": "A", "title": "E"}
        for i in range(12)
    ]
    step = plan_loop({"lane": "find", "id": "loop_1"}, jobs)
    assert step["status"] == "done"
    assert step["continue"] is False

    running = plan_loop({"lane": "find", "id": "loop_1"}, jobs[:2])
    assert running["continue"] is True
    assert "create_job" in running["instruction"]


def test_apply_loop_names_one_ready_job() -> None:
    step = plan_loop(
        {"lane": "apply"},
        [{"id": "greenhouse__1", "status": "apply_ready", "stopped": False, "company": "Acme", "title": "Staff"}],
    )
    assert step["job_id"] == "greenhouse__1"
    assert step["continue"] is True
    blocked = plan_loop({"lane": "apply"}, [])
    assert blocked["status"] == "blocked"


def test_pkce_verifier_rejects_values_outside_the_rfc_grammar() -> None:
    assert pkce_verifier_ok("a" * 64) is True
    assert pkce_verifier_ok("a" * 42) is False
    assert pkce_verifier_ok("a" * 129) is False
    assert pkce_verifier_ok("a" * 43 + " ") is False
    assert pkce_verifier_ok("é" * 64) is False


def test_oauth_callback_keeps_registered_query_parameters() -> None:
    uri = "https://client.example/callback?app=jobos&desk=1"
    merged = _with_query(uri, {"code": "abc", "state": "s1"})
    assert "app=jobos" in merged
    assert "desk=1" in merged
    assert "code=abc" in merged
    assert "state=s1" in merged
    denied = _with_query(uri, {"error": "access_denied", "state": "s1"})
    assert "app=jobos" in denied
    assert "error=access_denied" in denied


def test_redirect_uris_allow_loopback_and_https_only() -> None:
    assert redirect_uri_allowed("http://127.0.0.1:8787/callback") is True
    assert redirect_uri_allowed("https://example.com/oauth") is True
    assert redirect_uri_allowed("cursor://anysphere.cursor-mcp/oauth/callback") is True
    assert redirect_uri_allowed("http://evil.example/steal") is False
    assert redirect_uri_allowed("javascript:alert(1)") is False
    assert redirect_uri_allowed("https://example.com/cb#token") is False
