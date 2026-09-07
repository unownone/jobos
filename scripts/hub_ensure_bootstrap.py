# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "argon2-cffi>=23",
# ]
# ///
"""Mint unused HUB_BOOTSTRAP_TOKEN (jh_boot_*) and persist SHA-256 in SQLite.

Prints the admin signup URL. Does not start the server.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "board"))

from app.bootstrap import (  # noqa: E402
    ensure_bootstrap,
    env_path_for,
    format_signup_line,
    tokens_json_path_for,
)
from app.db import BoardDB  # noqa: E402
from app.settings import Settings, load_token_files, parse_env_file  # noqa: E402


def settings_for_board(board_dir: Path) -> Settings:
    env_path = board_dir / ".env"
    json_path = board_dir / "tokens.local.json"
    file_env = parse_env_file(env_path)
    merged = {**file_env, **os.environ}
    db_raw = merged.get("BOARD_DB", "data/board.db")
    db_path = Path(db_raw)
    if not db_path.is_absolute():
        db_path = board_dir / db_path
    host = merged.get("BOARD_HOST", "0.0.0.0") or "0.0.0.0"
    port_raw = merged.get("BOARD_PORT", "8787") or "8787"
    return Settings(
        board_dir=board_dir,
        db_path=db_path,
        host=host,
        port=int(port_raw),
        tokens=load_token_files() if board_dir == ROOT / "board" else {},
        public_url=(merged.get("HUB_PUBLIC_URL") or "").strip().rstrip("/"),
        bootstrap_token=(merged.get("HUB_BOOTSTRAP_TOKEN") or "").strip(),
        env_path=env_path,
        tokens_json_path=json_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Mint unused Job Hub bootstrap token")
    parser.add_argument(
        "--dir",
        default=str(ROOT / "board"),
        help="board directory (default: repo board/)",
    )
    args = parser.parse_args()
    board_dir = Path(args.dir).resolve()
    settings = settings_for_board(board_dir)
    db = BoardDB(settings.db_path)
    try:
        if db.admin_bootstrapped():
            print("admin already bootstrapped; bootstrap token disabled")
            print(f"Gitignored secrets: {env_path_for(settings)} {tokens_json_path_for(settings)}")
            return 0
        token = ensure_bootstrap(settings, db)
        if token:
            print(format_signup_line(settings, token))
        else:
            print("bootstrap token already minted (plaintext not in env); check board/.env if unused")
        print(f"Gitignored secrets: {env_path_for(settings)} {tokens_json_path_for(settings)}")
        print("Do not commit .env or tokens.local.json.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
