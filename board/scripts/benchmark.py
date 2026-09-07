# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "fastapi>=0.115",
#   "httpx>=0.27",
#   "python-multipart>=0.0.12",
# ]
# ///
"""Maintainer benchmark suite for the hunt board.

Measures API latency, small-load throughput, a synthetic skill pipeline,
and records sample token-burn rows. Prints p50/p95 summary tables.

  uv run board/scripts/benchmark.py
  uv run board/scripts/benchmark.py --url http://127.0.0.1:8787
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

BOARD_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOARD_DIR))

from app.constants import ROLES  # noqa: E402
from app.metrics import percentile  # noqa: E402


def _load_env() -> dict[str, str]:
    path = BOARD_DIR / ".env"
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _stats(samples_ms: list[float]) -> dict[str, float]:
    return {
        "n": len(samples_ms),
        "mean_ms": round(statistics.fmean(samples_ms), 3) if samples_ms else 0.0,
        "p50_ms": round(percentile(samples_ms, 50) or 0.0, 3),
        "p95_ms": round(percentile(samples_ms, 95) or 0.0, 3),
        "ops_per_s": round(1000.0 / (statistics.fmean(samples_ms) or 1.0), 2) if samples_ms else 0.0,
    }


class Client:
    def __init__(self, url: str | None, tokens: dict[str, str]) -> None:
        self.tokens = tokens
        self.url = (url or "").rstrip("/")
        self._http = None
        self._app_client = None
        if self.url:
            import httpx

            self._http = httpx.Client(base_url=self.url, timeout=30.0)
        else:
            from fastapi.testclient import TestClient

            from app.main import create_app
            from app.settings import Settings

            tmp = Path(os.environ.get("BOARD_BENCH_DIR") or BOARD_DIR / "data")
            tmp.mkdir(parents=True, exist_ok=True)
            settings = Settings(
                board_dir=BOARD_DIR,
                db_path=tmp / "benchmark.db",
                host="127.0.0.1",
                port=8787,
                tokens=tokens,
            )
            self._app_client = TestClient(create_app(settings))

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
        if self._app_client is not None:
            self._app_client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        role: str = "admin",
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any], float]:
        headers = {"X-Role": role, "X-Token": self.tokens[role], "X-Actor": "benchmark"}
        t0 = time.perf_counter()
        if self._http is not None:
            res = self._http.request(method, path, headers=headers, json=json_body)
            ms = (time.perf_counter() - t0) * 1000
            try:
                data = res.json()
            except Exception:
                data = {"raw": res.text}
            return res.status_code, data, ms
        assert self._app_client is not None
        res = self._app_client.request(method, path, headers=headers, json=json_body)
        ms = (time.perf_counter() - t0) * 1000
        try:
            data = res.json()
        except Exception:
            data = {"raw": res.text}
        return res.status_code, data, ms


def time_op(fn: Callable[[], tuple[int, dict[str, Any], float]], runs: int) -> list[float]:
    samples: list[float] = []
    for _ in range(runs):
        code, payload, ms = fn()
        if code >= 400:
            raise RuntimeError(f"benchmark op failed {code}: {payload}")
        samples.append(ms)
    return samples


def table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    lines = [fmt.format(*headers), fmt.format(*["-" * w for w in widths])]
    lines.extend(fmt.format(*row) for row in rows)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hunt board maintainer benchmarks")
    parser.add_argument("--url", default="", help="Live board URL. Empty = in-process TestClient.")
    parser.add_argument("--runs", type=int, default=25)
    parser.add_argument("--load", type=int, default=50, help="list/patch ops for throughput")
    args = parser.parse_args()

    file_env = _load_env()
    tokens = {
        role: os.environ.get(f"BOARD_TOKEN_{role.upper()}")
        or file_env.get(f"BOARD_TOKEN_{role.upper()}")
        or f"bench-token-{role}"
        for role in ROLES
    }
    if args.url:
        missing = [r for r in ROLES if not (os.environ.get(f"BOARD_TOKEN_{r.upper()}") or file_env.get(f"BOARD_TOKEN_{r.upper()}"))]
        if missing:
            print("live --url needs tokens in board/.env or BOARD_TOKEN_* env", file=sys.stderr)
            return 2

    client = Client(args.url or None, tokens)
    try:
        health_ms = time_op(lambda: client.request("GET", "/health", role="admin"), args.runs)

        stamp = int(time.time())
        create_samples: list[float] = []
        created_ids: list[str] = []
        for i in range(args.runs):
            job_id = f"bench__{stamp}-{i}"
            code, payload, ms = client.request(
                "POST",
                "/api/jobs",
                role="discovery",
                json_body={
                    "id": job_id,
                    "company": f"BenchCo-{stamp}",
                    "title": f"Engineer {stamp}-{i}",
                    "apply_url": f"https://example.invalid/bench/{stamp}/{i}",
                    "sources": ["benchmark"],
                    "status": "discovered",
                },
            )
            if code >= 400:
                raise RuntimeError(f"create failed {code}: {payload}")
            create_samples.append(ms)
            created_ids.append(payload["job"]["id"])

        list_samples = time_op(lambda: client.request("GET", "/api/jobs", role="apply"), args.load)
        patch_samples: list[float] = []
        for job_id in created_ids[: args.load]:
            code, payload, ms = client.request(
                "PATCH",
                f"/api/jobs/{job_id}",
                role="discovery",
                json_body={"notes": "bench patch"},
            )
            if code >= 400:
                raise RuntimeError(f"patch failed {code}: {payload}")
            patch_samples.append(ms)

        pipe_id = f"bench__pipe-{stamp}"
        hops: dict[str, float] = {}
        t_pipe = time.perf_counter()
        _, _, hops["create"] = client.request(
            "POST",
            "/api/jobs",
            role="discovery",
            json_body={
                "id": pipe_id,
                "company": f"PipeCo-{stamp}",
                "title": f"Staff {stamp}",
                "apply_url": f"https://example.invalid/pipe/{stamp}",
                "sources": ["benchmark"],
                "status": "discovered",
            },
        )
        _, _, hops["apply_ready"] = client.request(
            "PATCH",
            f"/api/jobs/{pipe_id}",
            role="discovery",
            json_body={
                "status": "apply_ready",
                "score": 4,
                "apply_packet": {"url": "https://example.invalid/pipe", "steps": ["open"]},
            },
        )
        _, _, hops["applied"] = client.request(
            "PATCH",
            f"/api/jobs/{pipe_id}",
            role="apply",
            json_body={
                "status": "applied",
                "owners": {"apply": "benchmark"},
                "proof": {"confirmation": "synthetic"},
            },
        )
        _, _, hops["outreach_touch"] = client.request(
            "PATCH",
            f"/api/jobs/{pipe_id}",
            role="outreach",
            json_body={
                "status": "waiting",
                "owners": {"outreach": "benchmark"},
                "outreach_packet": {"ask": "15-minute chat"},
            },
        )
        pipe_total_ms = (time.perf_counter() - t_pipe) * 1000

        _, _, stop_ms = client.request(
            "POST",
            f"/api/jobs/{pipe_id}/stop",
            role="admin",
            json_body={"reason": "benchmark complete"},
        )

        for tool, skill, tokens_n, dur in (
            ("exa-mcp", "discovery", 1200, hops["create"]),
            ("job-discovery", "discovery", 800, hops["apply_ready"]),
            ("job-apply", "apply", 1500, hops["applied"]),
            ("job-outreach", "outreach", 900, hops["outreach_touch"]),
        ):
            client.request(
                "POST",
                "/api/metrics/token_burn",
                role=skill,
                json_body={
                    "tool_name": tool,
                    "skill": skill,
                    "prompt_tokens": int(tokens_n * 0.7),
                    "completion_tokens": int(tokens_n * 0.3),
                    "duration_ms": dur,
                    "job_id": pipe_id,
                    "cost_usd": round(tokens_n * 0.000002, 6),
                },
            )

        summary_code, summary, _ = client.request("GET", "/api/metrics/summary", role="maintenance")
        if summary_code >= 400:
            summary = {}

        api_rows = [
            ["health", *[str(_stats(health_ms)[k]) for k in ("n", "mean_ms", "p50_ms", "p95_ms", "ops_per_s")]],
            ["create", *[str(_stats(create_samples)[k]) for k in ("n", "mean_ms", "p50_ms", "p95_ms", "ops_per_s")]],
            ["list", *[str(_stats(list_samples)[k]) for k in ("n", "mean_ms", "p50_ms", "p95_ms", "ops_per_s")]],
            ["patch", *[str(_stats(patch_samples)[k]) for k in ("n", "mean_ms", "p50_ms", "p95_ms", "ops_per_s")]],
            ["stop", *["1", f"{stop_ms:.3f}", f"{stop_ms:.3f}", f"{stop_ms:.3f}", f"{1000/stop_ms:.2f}"]],
        ]
        print("API latency / throughput")
        print(table(["op", "n", "mean_ms", "p50_ms", "p95_ms", "ops_per_s"], api_rows))
        print()
        print("Synthetic skill pipeline (create → apply_ready → applied → outreach touch)")
        print(table(
            ["hop", "ms"],
            [[name, f"{ms:.3f}"] for name, ms in hops.items()] + [["pipeline_total", f"{pipe_total_ms:.3f}"]],
        ))
        print()
        totals = summary.get("totals") or {}
        print("Token burn (this run + any prior rows in metrics store)")
        print(
            table(
                ["scope", "n", "total_tokens", "cost_usd", "p50_ms", "p95_ms"],
                [
                    [
                        "all",
                        str(summary.get("n", 0)),
                        str(totals.get("total_tokens", 0)),
                        str(totals.get("cost_usd", 0)),
                        str(totals.get("duration_ms_p50") or ""),
                        str(totals.get("duration_ms_p95") or ""),
                    ]
                ]
                + [
                    [
                        f"tool:{row['name']}",
                        str(row["n"]),
                        str(row["total_tokens"]),
                        str(row["cost_usd"]),
                        str(row.get("duration_ms_p50") or ""),
                        str(row.get("duration_ms_p95") or ""),
                    ]
                    for row in summary.get("by_tool") or []
                ]
                + [
                    [
                        f"skill:{row['name']}",
                        str(row["n"]),
                        str(row["total_tokens"]),
                        str(row["cost_usd"]),
                        str(row.get("duration_ms_p50") or ""),
                        str(row.get("duration_ms_p95") or ""),
                    ]
                    for row in summary.get("by_skill") or []
                ],
            )
        )
        print()
        print("mode:", "live " + args.url if args.url else "in-process TestClient")
        print("See board/BENCHMARKS.md for how to read these numbers.")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
