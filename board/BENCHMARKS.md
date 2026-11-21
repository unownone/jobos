# Hunt board benchmarks

Maintainer-owned measurements for the live coordination plane. Numbers below are **starting placeholders** until a hunt has real traffic. Re-run `curl health` on the box that hosts the board and paste a dated row into the table when you care.

## How to run

```bash
# in-process (no server; uses a throwaway SQLite under board/data/benchmark.db)
curl health

# against the live board (needs gitignored tokens in board/.env)
curl health --url http://127.0.0.1:8787 --runs 25 --load 50
```

Makefile: `make -C board bench` or `make board-bench`.

The suite prints:

1. **API latency / throughput** for `health`, `create`, `list`, `patch`, `stop` (mean, p50, p95, ops/sec)
2. **Synthetic skill pipeline** wall-clock: create → `apply_ready` → `applied` → outreach touch
3. **Token burn summary** from `POST /api/metrics/token_burn` (by tool, by skill/lane, totals)

Live data lives in gitignored `board/data/metrics.sqlite` and `board/data/metrics.jsonl`. Do not commit it.

## What “good” looks like (placeholders)

These are **local-box expectations**, not SLAs. A cold cloud agent, a tunnel, or a huge board will be slower. Fill the “measured” column after your first real run.

| Signal | Placeholder “good” | Why it matters |
| --- | --- | --- |
| `health` p95 | < 10 ms in-process, < 50 ms localhost | Uptime probe. If this is slow, the process is wedged. |
| `list` p95 | < 20 ms for hundreds of rows | Discovery/apply/outreach poll this. |
| `create` / `patch` p95 | < 30 ms localhost | Lane bots should not wait on the board. |
| `list` throughput | > 100 ops/sec localhost, small load | Sibling agents sharing a host. |
| Pipeline create → outreach touch | < 100 ms API-only | This is **board** time, not LLM time. Skill efficiency is the token-burn table. |
| Token burn / apply | Record every real apply; compare models later | Catch runaway tools before the bill does. |

If list p95 jumps after an import, run `POST /api/hygiene/vacuum` and check duplicate URLs.

## Token-burn schema

Agents (any role) POST to `/api/metrics/token_burn` with the maintenance or **their own** role token:

```json
{
  "tool_name": "exa-mcp",
  "skill": "discovery",
  "prompt_tokens": 1200,
  "completion_tokens": 400,
  "total_tokens": 1600,
  "cost_usd": 0.004,
  "duration_ms": 1820,
  "job_id": "remoteok__123"
}
```

`skill` / `lane` should be `discovery` | `apply` | `outreach` | `maintain` | `research`. Extra keys are stored in `extra` for later fields (model name, cache hits, etc.).

How we’ll use this:

- Kill or swap tools whose tokens-per-shortlist or tokens-per-applied are outliers
- Compare Exa vs local deep-research on the same jobs
- See whether apply copy or outreach research is the expensive lane
- Keep the board itself honest: API ms vs model ms should not be confused

## Interpretation notes

- **Board latency** is SQLite + FastAPI on one host. It should be boring. If it is not, that is a maintainer bug, not a model problem.
- **Pipeline ms** in the benchmark is synthetic and uses tiny JSON. Real discovery still spends most of its time on portals and research MCPs. Log those under token burn.
- **Cost USD** is optional and only as good as the agent’s estimate. Prefer tokens; fill cost when the vendor bill is known.
- Empty metrics after a cycle means agents are not logging. That is the first efficiency bug.
