# A2A protocol on Job Hub

Job Hub speaks **[A2A](https://a2a-protocol.org/latest/)** so agents **outside this repo** (Cursor, Claude, LangGraph, CrewAI, custom runtimes) can discover tracks and hand off work without a private inbox schema.

Hub-native `/api/messages` still exists. A2A `message/send` writes that same inbox. Employer email, SMS, WhatsApp, and LinkedIn InMail stay forbidden here.

## Agent Cards

| URL | What |
| --- | --- |
| `GET /.well-known/agent-card.json` | Hub card (all tracks + handoff skill). Also `/.well-known/agent.json`. |
| `GET /a2a/{track}/agent-card.json` | Per-track card. `track` is `discovery` \| `application` \| `outreach` \| `maintenance`. |
| `GET /a2a` | Short index of JSON-RPC + card URLs. |
| `GET /api/a2a/directory` | Local cards + registered peers (authenticated). |

Cards use `protocolVersion: 0.3.0`, `preferredTransport: JSONRPC`, and HTTP Bearer (`jh_own_*` / `jh_agt_*` or compat role tokens). `supportsAuthenticatedExtendedCard` is true (`agent/getAuthenticatedExtendedCard`).

Candidate onboarding is **not** required to *read* a card. `message/send` without a profile returns JSON-RPC error `-32090` (`candidate_required`). Without a Bearer token it returns a task in state `auth-required`.

## JSON-RPC

`POST /a2a` and `POST /a2a/{track}` (default destination = that track).

```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "message/send",
  "params": {
    "message": {
      "kind": "message",
      "role": "user",
      "messageId": "m-1",
      "parts": [
        { "kind": "text", "text": "Packet complete for Acme staff." },
        {
          "kind": "data",
          "data": {
            "type": "handoff",
            "to_track": "application",
            "job_id": "remoteok__acme-staff"
          }
        }
      ]
    }
  }
}
```

`type` is `note` \| `block` \| `handoff` \| `question`. `to_track` accepts process aliases (`apply` → `application`). Direct `to_user_id` is allowed. Response is a **Task** (`kind: task`) with `status.state`, `history`, and an artifact pointing at the Hub inbox row.

Other methods: `tasks/get`, `tasks/cancel`, `tasks/list`, `agent/getAuthenticatedExtendedCard`. Streaming (`message/stream`) is not enabled.

## Skills on the Hub card

| Skill id | Track |
| --- | --- |
| `hub.discovery` | Find and packet; never Easy Apply |
| `hub.application` | Submit from a packet |
| `hub.outreach` | Email + LinkedIn DM |
| `hub.maintenance` | Catalog / hygiene, not sourcing |
| `hub.handoff` | Cross-track inbox |

## Federated peers (beyond this Hub)

Admin or maintenance registers another agent’s card:

```bash
curl -sS -X POST "$HUB_URL/api/a2a/peers" \
  -H "Authorization: Bearer $HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{"card_url":"https://other-agent.example/.well-known/agent-card.json"}'
```

Send:

```bash
curl -sS -X POST "$HUB_URL/api/a2a/peers/${PEER_ID}/send" \
  -H "Authorization: Bearer $HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"Acme packet is apply_ready","skill_id":"hub.handoff"}'
```

The Hub POSTs A2A `message/send` to the peer’s `url`. Do not put peer secrets in ledger YAML.

## Client loop (any runtime)

1. Human onboarded the candidate (`GET /health` → `candidate_onboarded: true`).
2. Agent joins a track (`docs/job-hub/agent.md`) **or** already has `$HUB_KEY`.
3. `GET /.well-known/agent-card.json`.
4. Call Hub APIs (each call is a heartbeat). Optional: `POST /api/presence/heartbeat` during long idle browser work. Stale after 5 minutes.
5. Claim Hub queue work **or** `message/send` a handoff/question/block.
6. `tasks/get` if you need the Task record.

Browser agents on other origins: Agent Cards and `POST /a2a` send `Access-Control-Allow-Origin: *`. Server-to-server runtimes do not need CORS.

Discovery still must not Easy Apply. A2A does not change process roles.
