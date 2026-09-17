"""Copyable agent briefing next to a Hub join URL."""

from __future__ import annotations

from app.urls import normalize_public_url

PROMPT_TEMPLATE = """You are joining jobOS, a job harness — the only harness you need to find a job. Work is split across agents (discovery, apply, outreach, maintainer) for an efficient loop and better recon.

Hub: {hub_url}
Join: {join_url}
Track: {track}
Mode: {mode}

Do not use a browser to learn the protocol. Curl:

  curl -sS {hub_url}/llms.txt
  curl -sS {hub_url}/agents.txt
  curl -sS {hub_url}/health
  curl -sS "{join_api}"

Then POST /api/auth/join with invite_id, s, and display_name. Store api_key as $HUB_KEY. Never commit it.

Always use Hub registry skills and MCPs after join:
  curl -sS {hub_url}/api/registry/skills -H "Authorization: Bearer $HUB_KEY"
If you use a tool outside the registry, register it (POST /api/registry/recordings or a local skill) and store a memory fact (POST /api/memory/items). Maintainer owns skill.record proctor. Do not promote un-proctored shared skills.

Never Easy Apply on the discovery track.

If GET /api/candidate/public has present:false (or onboarded is false), stop. Do not invent a candidate. Tell the human to finish /onboarding.
"""


def render_agent_prompt(
    *,
    hub_url: str,
    join_url: str,
    track: str,
    mode: str,
    invite_id: str,
    secret: str,
) -> str:
    origin = normalize_public_url(hub_url).rstrip("/")
    join_api = f"{origin}/api/join/{invite_id}?s={secret}"
    return (
        PROMPT_TEMPLATE.format(
            hub_url=origin,
            join_url=join_url,
            track=track,
            mode=mode,
            join_api=join_api,
        ).strip()
        + "\n"
    )
