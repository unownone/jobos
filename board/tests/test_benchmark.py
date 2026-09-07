"""In-process maintainer benchmark smoke test."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.constants import ROLES

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark.py"


def test_benchmark_in_process(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOARD_BENCH_DIR", str(tmp_path))
    for role in ROLES:
        monkeypatch.setenv(f"BOARD_TOKEN_{role.upper()}", f"bench-token-{role}")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--runs", "3", "--load", "3"],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert "API latency / throughput" in result.stdout
    assert "Synthetic skill pipeline" in result.stdout
    assert "Token burn" in result.stdout
    assert "create" in result.stdout
    assert result.returncode == 0
