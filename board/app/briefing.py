"""Agent briefing documents: llms.txt and agents.txt as text/plain.

Git files are the source. Hub substitutes the live public origin.
Agents curl these; they do not scrape HTML.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.settings import Settings
from app.urls import resolve_public_url

BRIEFING_NAMES = ("llms.txt", "agents.txt")
HUB_PLACEHOLDER = "{{HUB_URL}}"


def repo_root_for(settings: Settings) -> Path:
    return settings.repo_root or settings.board_dir.parent


def briefing_search_paths(settings: Settings, name: str) -> list[Path]:
    root = repo_root_for(settings)
    return [
        root / name,
        root / "docs" / name,
        Path(__file__).resolve().parent.parent.parent / name,
    ]


def load_briefing_template(settings: Settings, name: str) -> str:
    if name not in BRIEFING_NAMES:
        raise ValueError(f"unknown briefing {name!r}")
    for path in briefing_search_paths(settings, name):
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(name)


def hub_origin(settings: Settings) -> str:
    origin = (settings.public_url or "").strip().rstrip("/")
    if origin:
        return origin
    return resolve_public_url(listen_host="127.0.0.1", listen_port=settings.port)


def render_briefing(settings: Settings, name: str) -> str:
    text = load_briefing_template(settings, name)
    return text.replace(HUB_PLACEHOLDER, hub_origin(settings))


def briefing_response(settings: Settings, name: str) -> PlainTextResponse:
    body = render_briefing(settings, name)
    return PlainTextResponse(
        body,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


def create_briefing_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["briefing"])

    @router.get("/llms.txt")
    @router.get("/.well-known/llms.txt")
    def llms_txt() -> PlainTextResponse:
        return briefing_response(settings, "llms.txt")

    @router.get("/agents.txt")
    @router.get("/.well-known/agents.txt")
    def agents_txt() -> PlainTextResponse:
        return briefing_response(settings, "agents.txt")

    return router
