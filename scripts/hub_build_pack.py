#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "argon2-cffi>=23",
#   "pyyaml>=6",
#   "psycopg[binary]>=3.2",
# ]
# ///
"""Build an immutable Job Hub skill/MCP pack from the operator checkout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BOARD = Path(__file__).resolve().parents[1] / "board"
sys.path.insert(0, str(BOARD))

from app.pack import PackStore  # noqa: E402
from app.settings import Settings, load_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild Hub onboarding pack snapshots")
    parser.add_argument("--dir", type=Path, default=None, help="board directory")
    parser.add_argument("--repo", type=Path, default=None, help="git checkout root")
    args = parser.parse_args()
    if args.dir is None:
        settings = load_settings()
    else:
        board = args.dir.resolve()
        repo = (args.repo or board.parent).resolve()
        settings = Settings(
            board_dir=board,
            db_path=board / "data" / "board.db",
            host="127.0.0.1",
            port=8787,
            tokens={},
            repo_root=repo,
            packs_dir=board / "data" / "packs",
        )
    meta = PackStore(settings).rebuild()
    print(
        json.dumps(
            {
                "pack_sha": meta.pack_sha,
                "git_sha": meta.git_sha,
                "built_at": meta.built_at,
                "catalog_updated_at": meta.catalog_updated_at,
                "files": meta.files,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
