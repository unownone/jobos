"""Invite prompt rendering (no FastAPI)."""

from __future__ import annotations

from app.invite_prompt import render_agent_prompt


def test_agent_prompt_names_jobos_and_registry() -> None:
    text = render_agent_prompt(
        hub_url="https://hub.example.test",
        join_url="https://hub.example.test/join/inv_1?s=secret",
        track="discovery",
        mode="owner_then_agents",
        invite_id="inv_1",
        secret="secret",
    )
    assert "jobOS" in text
    assert "https://hub.example.test/llms.txt" in text
    assert "https://hub.example.test/agents.txt" in text
    assert "/api/registry/skills" in text
    assert "Never Easy Apply" in text
    assert "do not invent a candidate" in text.lower()
    assert "skill.record" in text
    assert "discovery" in text
