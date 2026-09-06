#!/usr/bin/env python3
"""Non-interactive runner for dzhng/open-deep-research (HTTP API).

Job Apply OS operators should prefer Exa MCP when it is attached. Use this
CLI when Exa is missing and FIRECRAWL_KEY + OPENAI_KEY (or FIREWORKS_KEY)
are present.

Maps Job Apply OS env names onto the upstream .env.local names, starts
`npm run api` if nothing is listening on the port, POSTs /api/research,
prints JSON, and optionally writes a compressed markdown brief.

Never prints API keys.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "agent-tools" / "open-deep-research"
DEFAULT_PORT = 3051


def dest_dir() -> Path:
    return Path(os.environ.get("JOBOS_DEEP_RESEARCH_DIR", str(DEFAULT_DIR)))


def port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def first_present(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def write_env_local(path: Path) -> None:
    firecrawl = first_present("FIRECRAWL_KEY", "FIRECRAWL_API_KEY")
    openai = first_present("OPENAI_KEY", "OPENAI_API_KEY")
    fireworks = first_present("FIREWORKS_KEY", "FIREWORKS_API_KEY")
    endpoint = first_present("OPENAI_ENDPOINT")
    model = first_present("CUSTOM_MODEL", "OPENAI_MODEL")
    base_url = first_present("FIRECRAWL_BASE_URL")
    lines = [
        f'FIRECRAWL_KEY="{firecrawl}"',
        f'OPENAI_KEY="{openai}"',
        f'CONTEXT_SIZE="{os.environ.get("CONTEXT_SIZE", "128000")}"',
        f'FIRECRAWL_CONCURRENCY="{os.environ.get("FIRECRAWL_CONCURRENCY", "2")}"',
    ]
    if fireworks:
        lines.append(f'FIREWORKS_KEY="{fireworks}"')
    if endpoint:
        lines.append(f'OPENAI_ENDPOINT="{endpoint}"')
    if model:
        lines.append(f'CUSTOM_MODEL="{model}"')
    if base_url:
        lines.append(f'FIRECRAWL_BASE_URL="{base_url}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def require_keys() -> None:
    if not first_present("FIRECRAWL_KEY", "FIRECRAWL_API_KEY"):
        raise SystemExit(
            "missing FIRECRAWL_KEY (or FIRECRAWL_API_KEY). "
            "See docs/catalogs/deep-research.md"
        )
    if not (
        first_present("OPENAI_KEY", "OPENAI_API_KEY")
        or first_present("FIREWORKS_KEY", "FIREWORKS_API_KEY")
    ):
        raise SystemExit(
            "missing OPENAI_KEY / OPENAI_API_KEY or FIREWORKS_KEY. "
            "See docs/catalogs/deep-research.md"
        )


def start_api(repo: Path, port: int) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["PORT"] = str(port)
    proc = subprocess.Popen(
        ["npm", "run", "api"],
        cwd=repo,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    deadline = time.time() + 45
    while time.time() < deadline:
        if proc.poll() is not None:
            err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
            raise SystemExit(f"deep-research API exited early:\n{err}")
        if port_open("127.0.0.1", port):
            return proc
        time.sleep(0.4)
    proc.terminate()
    raise SystemExit("deep-research API did not bind to the port in time")


def post_research(port: int, query: str, depth: int, breadth: int) -> dict:
    payload = json.dumps(
        {"query": query, "depth": depth, "breadth": breadth}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/research",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"research API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"research API unreachable: {exc}") from exc
    if not isinstance(body, dict):
        raise SystemExit("research API returned a non-object")
    return body


def brief_markdown(query: str, result: dict) -> str:
    learnings = result.get("learnings") or []
    urls = result.get("visitedUrls") or []
    answer = str(result.get("answer") or "").strip()
    learning_lines = "\n".join(f"- {item}" for item in learnings) or "- (none)"
    source_lines = "\n".join(f"- {item}" for item in urls) or "- (none)"
    return (
        f"# Research brief\n"
        f"- Query: {query}\n"
        f"- Live?: unknown (operator must confirm posting URLs)\n"
        f"- What they do: {answer or '(see learnings)'}\n"
        f"- Learnings:\n{learning_lines}\n"
        f"- Sources:\n{source_lines}\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run dzhng/open-deep-research non-interactively for Job Apply OS."
    )
    parser.add_argument("--query", required=True, help="Specific research instruction")
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--breadth", type=int, default=3)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write the raw API JSON here (gitignored cache is fine)",
    )
    parser.add_argument(
        "--brief-out",
        type=Path,
        default=None,
        help="Write a compressed markdown brief here",
    )
    parser.add_argument(
        "--setup-only",
        action="store_true",
        help="Write .env.local and exit without calling the API",
    )
    args = parser.parse_args()

    repo = dest_dir()
    if not (repo / "package.json").exists():
        raise SystemExit(
            f"open-deep-research is not installed at {repo}. "
            "Run: bash scripts/setup_deep_research.sh"
        )

    require_keys()
    write_env_local(repo / ".env.local")
    if args.setup_only:
        print(json.dumps({"ok": True, "env_local": str(repo / ".env.local")}))
        return

    started: subprocess.Popen[bytes] | None = None
    try:
        if not port_open("127.0.0.1", args.port):
            started = start_api(repo, args.port)
        result = post_research(args.port, args.query, args.depth, args.breadth)
    finally:
        if started is not None:
            started.terminate()
            try:
                started.wait(timeout=5)
            except subprocess.TimeoutExpired:
                started.kill()

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.brief_out:
        args.brief_out.parent.mkdir(parents=True, exist_ok=True)
        args.brief_out.write_text(
            brief_markdown(args.query, result), encoding="utf-8"
        )
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
