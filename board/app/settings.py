"""Load board settings from env / gitignored token files. Never ships secrets."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.constants import ROLES, TOKEN_ENV
from app.urls import resolve_public_url

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
    public_url: str = ""
    bootstrap_token: str = ""
    env_path: Path | None = None
    tokens_json_path: Path | None = None
    repo_root: Path | None = None
    packs_dir: Path | None = None
    database_url: str = ""
    amqp_url: str = ""
    queue_adapter: str = "memory"
    blob_root: Path | None = None
    blob_adapter: str = "filesystem"


def load_settings() -> Settings:
    file_env = parse_env_file(ENV_PATH)
    merged = {**file_env, **os.environ}
    db_raw = merged.get("BOARD_DB", "data/board.db")
    db_path = Path(db_raw)
    if not db_path.is_absolute():
        db_path = BOARD_DIR / db_path
    host = merged.get("BOARD_HOST", "0.0.0.0") or "0.0.0.0"
    port_raw = merged.get("BOARD_PORT", "8787") or "8787"
    public_url = resolve_public_url(
        public_url=merged.get("HUB_PUBLIC_URL") or "",
        public_host=merged.get("HUB_PUBLIC_HOST") or "",
        listen_host=host,
        listen_port=int(port_raw),
    )
    bootstrap_token = (merged.get("HUB_BOOTSTRAP_TOKEN") or "").strip()
    database_url = (merged.get("DATABASE_URL") or merged.get("TEST_DATABASE_URL") or "").strip()
    repo_raw = (merged.get("HUB_REPO_ROOT") or "").strip()
    packs_raw = (merged.get("HUB_PACKS_DIR") or "").strip()
    repo_root = Path(repo_raw) if repo_raw else BOARD_DIR.parent
    if packs_raw:
        packs_dir = Path(packs_raw)
        if not packs_dir.is_absolute():
            packs_dir = BOARD_DIR / packs_dir
    else:
        packs_dir = db_path.parent / "packs"
    amqp_url = (merged.get("AMQP_URL") or merged.get("RABBITMQ_URL") or "").strip()
    queue_adapter = (merged.get("QUEUE_ADAPTER") or ("rabbitmq" if amqp_url else "memory")).strip().lower()
    blob_adapter = (merged.get("BLOB_ADAPTER") or "filesystem").strip().lower()
    blob_raw = (merged.get("BLOB_ROOT") or "").strip()
    if blob_raw:
        blob_root = Path(blob_raw)
        if not blob_root.is_absolute():
            blob_root = BOARD_DIR / blob_root
    else:
        blob_root = db_path.parent / "blobs"
    return Settings(
        board_dir=BOARD_DIR,
        db_path=db_path,
        host=host,
        port=int(port_raw),
        tokens=load_token_files(),
        public_url=public_url,
        bootstrap_token=bootstrap_token,
        env_path=ENV_PATH,
        tokens_json_path=TOKENS_JSON_PATH,
        repo_root=repo_root,
        packs_dir=packs_dir,
        database_url=database_url,
        amqp_url=amqp_url,
        queue_adapter=queue_adapter,
        blob_root=blob_root,
        blob_adapter=blob_adapter,
    )
