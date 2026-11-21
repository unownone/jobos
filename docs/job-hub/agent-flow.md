# Agent flow

This is the path to use. The older invite and role API stays.

One admin. No team collaboration is required. Agents read, find, and add skills, MCPs, and memories for the lanes the human picks. Humans observe, leave steers, and do not have to re-prompt each step.

## Connect

1. Log in at `/login`.
2. Open `/connect`.
3. Add the shown URL (`/mcp` on that origin) to the AI’s MCP settings.
4. The AI receives `401` with `WWW-Authenticate` pointing at `/.well-known/oauth-protected-resource/mcp`.
5. It registers, opens `/oauth/authorize`, and the admin approves.
6. `POST /oauth/token` returns an access token (1 hour) and a refresh token (90 days). Refresh rotates. Reusing an old refresh token revokes the grant.
7. `POST /mcp` speaks MCP. `DELETE /mcp` ends the agent session. The grant can initialize a new one.

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

Job tools: `list_jobs`, `get_job`, `create_job` (find), `update_job` (lane required), `list_people` (outreach).

## Human page

`/connect` is admin-only. It shows the MCP URL, connected clients, lanes, capabilities, loops, skill use, and a steer box. Revoke drops the grant.

`GET /api/agent/status`, `POST /api/agent/steers`, `POST /api/agent/grants/{id}/revoke`.
