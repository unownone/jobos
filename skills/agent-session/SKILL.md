---
name: agent-session
description: Run a jobOS agent session over MCP. Ask the human which lanes this session should run, check browser and email before find, apply, or outreach, and keep a loop going without waiting for another prompt.
role: agent
tags: [agent]
kind: skill
slug: agent-session
reproducible: true
inputs: [session]
outputs: [lanes, loop]
---

# Agent session

You are one agent. You are not stuck in a single lane. The human watches, leaves steers, and picks lanes. You do the work.

Use this when the human says **get started**, **find jobs**, **apply jobs**, or **outreach jobs**, or when you have just connected to jobOS MCP (`/mcp`).

## Before any hunt

1. Call `get_started`.
2. If lanes are empty, call `ask_session_lanes` and ask that question. Wait for the human. Then `set_session_lanes` with exactly what they chose. They may pick more than one of `find`, `apply`, `outreach`. Do not choose for them.
3. Call `report_capabilities`. `browser` is true only if you can drive a real browser in this client. `email` is true only if a mailbox is connected. False is a valid answer.
4. Call `evaluate_lane` for each chosen lane. If `can` is false, tell the human what is missing and do not start that lane.
5. Call `read_skill` for `agent-session` once, then the lane skill (`job-discovery`, `job-apply`, `job-outreach`). Call `record_use` when you follow a skill or an external MCP.
6. Call `recall_memory` and `read_steers` before the first search, submit, or email.

## Capability rules

- **Find** needs a browser. Without one, discovery does not work. Do not pretend a web search replaces the boards that need a browser.
- **Apply** needs a browser. Without one, do not submit.
- **Outreach** needs an email connection. A browser is optional. Do not send mail you cannot attach a resume PDF to. No SMS.

## Loop

When a lane can run, call `start_loop` for that lane. Then call `next_loop` after every step until status is `done` or `blocked`. Do not wait for the human to ask again. A steer on the loop is an instruction, not a new prompt you must request.

Find never Easy Applies. Apply follows the packet. Outreach attaches the resume PDF on email.

## Memory

Write a memory fact only when another session would otherwise rediscover it: a dead board, a portal quirk, a missing connector. Do not store job descriptions or secrets.

## Older API

Invite keys and `X-Role` still work for bots that joined that way. If you are on this MCP connection, use the MCP tools. Do not ask for a second Hub key.
