"""Load board settings from env / gitignored token files. Never ships secrets."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.constants import ROLES, TOKEN_ENV

BOARD_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BOARD_DIR / ".env"
TOKENS_JSON_PATH = BOARD_DIR / "tokens.local.json"


def parse_env_file(path: Path) -> dict[str, str]:
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


def _token_map_from_env(values: dict[str, str]) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for role, env_name in TOKEN_ENV.items():
        raw = values.get(env_name, "").strip()
        if raw:
            tokens[role] = raw
    return tokens


def load_token_files() -> dict[str, str]:
    """Merge tokens.local.json then .env. Process env wins last."""
    tokens: dict[str, str] = {}
    if TOKENS_JSON_PATH.is_file():
        payload = json.loads(TOKENS_JSON_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            for role in ROLES:
                value = str(payload.get(role) or "").strip()
                if value:
                    tokens[role] = value
    tokens.update(_token_map_from_env(parse_env_file(ENV_PATH)))
    tokens.update(_token_map_from_env(os.environ))
    return tokens


@dataclass(frozen=True)
class Settings:
    board_dir: Path
    db_path: Path
    host: str
    port: int
    tokens: dict[str, str]


def load_settings() -> Settings:
    file_env = parse_env_file(ENV_PATH)
    merged = {**file_env, **os.environ}
    db_raw = merged.get("BOARD_DB", "data/board.db")
    db_path = Path(db_raw)
    if not db_path.is_absolute():
        db_path = BOARD_DIR / db_path
    host = merged.get("BOARD_HOST", "0.0.0.0") or "0.0.0.0"
    port_raw = merged.get("BOARD_PORT", "8787") or "8787"
    return Settings(
        board_dir=BOARD_DIR,
        db_path=db_path,
        host=host,
        port=int(port_raw),
        tokens=load_token_files(),
    )
