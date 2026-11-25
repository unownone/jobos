# Agent flow

This is the path to use. The older invite and role API stays as a fallback.

One admin. No team collaboration is required. Agents read, find, and add skills, MCPs, and memories for the lanes the human picks. Humans observe, leave steers, and do not have to re-prompt each step.

## Connect (MCP-first)

**Preferred — invite paste**

1. Admin opens Invites and creates an MCP invite (bootstraps a long-lived Hub API key).
2. Copy a client block (Cursor, Claude, Grok, or Codex) and paste it into the AI’s MCP settings.
3. The block points at `{HUB_PUBLIC_URL}/mcp` with `Authorization: Bearer jh_agt_…` / `jh_own_…`.
4. That Bearer key lasts ~90 days on MCP. Ask the agent to call `get_started` and operate only through MCP tools.

Set `HUB_PUBLIC_URL=https://ikr.one` (or `HUB_PUBLIC_HOST=ikr.one`) in production so paste snippets and join links use the public host, not `*.run.app`.

**Alternate — OAuth on /connect**

1. Log in at `/login`.
2. Open `/connect`.
3. Add the shown URL (`/mcp` on that origin) to the AI’s MCP settings.
4. The AI receives `401` with `WWW-Authenticate` pointing at `/.well-known/oauth-protected-resource/mcp`.
5. It registers, opens `/oauth/authorize`, and the admin approves.
6. `POST /oauth/token` returns an access token (~24 hours) and a refresh token (90 days). Refresh rotates. Reusing an old refresh token revokes the grant.
7. `POST /mcp` speaks MCP. `DELETE /mcp` ends the agent session. The grant can initialize a new one.

Browser `/join/{id}?s=…` remains a fallback that also returns MCP client snippets after redeem.

## Session

The agent session belongs to the connection. jobOS does not pick lanes.

- `ask_session_lanes` — the question to ask the human.
- `set_session_lanes` — store `find`, `apply`, and/or `outreach` after they answer.
- `report_capabilities` — `browser` and `email`, honestly.
- `evaluate_lane` — find and apply need a browser. Outreach needs email. Unreported capabilities cannot pass.

## Work

`get_started` is the first tool. Prompts the human can say: get started, find jobs, apply jobs, outreach jobs.

`start_loop` then `next_loop` until the loop is `done` or `blocked`. The agent calls `next_loop` again without a new human message.

`read_skill` prefixes the playbook with the capability gate. `record_use` stores which skill or MCP the agent actually used. `recall_memory` / `write_memory` are the memory pods. `read_steers` returns notes the admin saved on `/connect`.

Parity tools (mirror Hub HTTP): jobs (`list`/`get`/`create`/`update`/`delete`/`stop`/`pause`/`resume`), queue (`push`/`claim`/`ack`/`nack`/`mine`/`list`), memory (`recall`/`list`/`write`/`patch`/`move`/`delete`/`solidify`/`pods`), candidate (`get`/`put`/`status`/`resume get|put`), invites (`list`/`create`/`revoke`), registry (`skills` list/get/create/patch/fork, `mcps` list/get, recordings list/get/create/proctor/promote/decline), people (`list`/`create`/`get`/`update`), messages (`list`/`create`/`read`), presence (`list`/`get`/`heartbeat`), events, meta, export_ledger, whoami, onboarding.

## Human page

`/connect` is admin-only. It shows the MCP URL, connected clients, lanes, capabilities, loops, skill use, and a steer box. Revoke drops the grant.

`GET /api/agent/status`, `POST /api/agent/steers`, `POST /api/agent/grants/{id}/revoke`.
