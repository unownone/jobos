# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "psycopg[binary]>=3.2",
#   "pyyaml>=6",
# ]
# ///
"""Write Hub Postgres jobs/people/events to a ledger directory. Optional/on-demand. Strips secrets."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "board"))

from app.db import BoardDB  # noqa: E402
from app.export import build_ledger_files  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Hub Postgres to ledger YAML+jsonl (no secrets)")
    parser.add_argument("--db", default=str(ROOT / "board" / "data" / "board.db"))
    parser.add_argument("--dest", default=str(ROOT / "ledger"))
    args = parser.parse_args()
    db = BoardDB(Path(args.db))
    dest = Path(args.dest)
    files = build_ledger_files(db)
    for rel, text in files.items():
        inner = Path(rel)
        if inner.parts and inner.parts[0] == "ledger":
            inner = Path(*inner.parts[1:]) if len(inner.parts) > 1 else Path(".")
        path = dest / inner
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
