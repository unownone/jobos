"""Token generator writes gitignored files and never hardcodes secrets."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "board_gen_tokens.py"
ROLES = {"discovery", "apply", "outreach", "admin", "maintenance"}


def test_gen_tokens_creates_random_values(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--dir", str(tmp_path), "--print"],
        check=True,
        capture_output=True,
        text=True,
    )
    env_path = tmp_path / ".env"
    json_path = tmp_path / "tokens.local.json"
    assert env_path.is_file()
    assert json_path.is_file()
    tokens = json.loads(json_path.read_text(encoding="utf-8"))
    assert ROLES <= set(tokens)
    assert set(tokens) - ROLES <= {"bootstrap"}
    role_tokens = {key: tokens[key] for key in ROLES}
    assert all(len(v) >= 32 for v in role_tokens.values())
    assert len(set(role_tokens.values())) == 5
    env_text = env_path.read_text(encoding="utf-8")
    assert "DO NOT COMMIT" in env_text
    assert "test-token" not in env_text
    for role, token in role_tokens.items():
        assert f"{role}={token}" in result.stdout


def test_gen_tokens_idempotent_without_rotate(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, str(SCRIPT), "--dir", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    first = json.loads((tmp_path / "tokens.local.json").read_text(encoding="utf-8"))
    subprocess.run(
        [sys.executable, str(SCRIPT), "--dir", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    second = json.loads((tmp_path / "tokens.local.json").read_text(encoding="utf-8"))
    assert first == second
    subprocess.run(
        [sys.executable, str(SCRIPT), "--dir", str(tmp_path), "--rotate", "admin"],
        check=True,
        capture_output=True,
        text=True,
    )
    third = json.loads((tmp_path / "tokens.local.json").read_text(encoding="utf-8"))
    assert third["admin"] != first["admin"]
    assert third["discovery"] == first["discovery"]


def test_gen_tokens_preserves_bootstrap_secret(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, str(SCRIPT), "--dir", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    env_path = tmp_path / ".env"
    json_path = tmp_path / "tokens.local.json"
    env_path.write_text(
        env_path.read_text(encoding="utf-8") + "HUB_BOOTSTRAP_TOKEN=jh_boot_keepme\n",
        encoding="utf-8",
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["bootstrap"] = "jh_boot_keepme"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    subprocess.run(
        [sys.executable, str(SCRIPT), "--dir", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    env_text = env_path.read_text(encoding="utf-8")
    assert "HUB_BOOTSTRAP_TOKEN=jh_boot_keepme" in env_text
    tokens = json.loads(json_path.read_text(encoding="utf-8"))
    assert tokens["bootstrap"] == "jh_boot_keepme"
