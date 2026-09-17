"""Unit tests for agent briefing render (no FastAPI)."""

from __future__ import annotations

from pathlib import Path

from app.briefing import BRIEFING_NAMES, render_briefing
from app.constants import COMING_SOON_ROLES
from app.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        board_dir=tmp_path,
        db_path=tmp_path / "board.db",
        host="127.0.0.1",
        port=8787,
        tokens={},
        public_url="https://hub.example.test",
        repo_root=Path(__file__).resolve().parents[2],
    )


def test_llms_txt_substitutes_hub_origin(tmp_path: Path) -> None:
    text = render_briefing(_settings(tmp_path), "llms.txt")
    assert "{{HUB_URL}}" not in text
    assert "https://hub.example.test" in text
    assert "jobOS is a job harness" in text
    assert "curl -sS \"$HUB_URL/api/registry/skills\"" in text or "/api/registry/skills" in text
    assert "Easy Apply" in text


def test_agents_txt_has_roles_and_coming_soon(tmp_path: Path) -> None:
    text = render_briefing(_settings(tmp_path), "agents.txt")
    assert "discovery" in text
    assert "maintenance" in text
    assert "coming soon" in text.lower()
    assert "review" in text
    assert "resume" in text
    assert "skill.record" in text
    ids = {row["id"] for row in COMING_SOON_ROLES}
    assert ids == {"review", "resume"}


def test_briefing_names_are_the_public_pair() -> None:
    assert BRIEFING_NAMES == ("llms.txt", "agents.txt")
