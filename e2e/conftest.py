"""Live Hub for Playwright: Docker Compose when available, else local uvicorn."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.e2e.yml"
COMPOSE_PROJECT = "jobos-e2e"
DEFAULT_COMPOSE_URL = "http://127.0.0.1:18787"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    marker = pytest.mark.browser
    for item in items:
        item.add_marker(marker)


@dataclass
class HubHandle:
    url: str
    backend: str
    bootstrap_token: str = ""
    stop: Callable[[], None] | None = None


def _wait_http(url: str, timeout_s: float = 120) -> None:
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=3) as res:
                if res.status == 200:
                    return
                last = f"status {res.status}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = str(exc)
        time.sleep(1)
    raise RuntimeError(f"Hub at {url} did not become healthy: {last}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _docker_compose_available() -> bool:
    if os.environ.get("E2E_BACKEND") == "local":
        return False
    if not shutil.which("docker"):
        return False
    probe = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.returncode == 0


def _start_compose() -> HubHandle:
    cmd = [
        "docker",
        "compose",
        "-f",
        str(COMPOSE_FILE),
        "-p",
        COMPOSE_PROJECT,
        "up",
        "-d",
        "--build",
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)
    url = os.environ.get("E2E_HUB_URL") or DEFAULT_COMPOSE_URL
    _wait_http(url, timeout_s=180)

    def stop() -> None:
        if os.environ.get("E2E_KEEP") == "1":
            return
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_FILE),
                "-p",
                COMPOSE_PROJECT,
                "down",
                "-v",
            ],
            cwd=ROOT,
            check=False,
        )

    return HubHandle(url=url, backend="compose", stop=stop)


def _start_local() -> HubHandle:
    import pgserver

    data_dir = Path(os.environ.get("E2E_PGDATA") or "/tmp/jobos-e2e-pg")
    data_dir.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(data_dir, cleanup_mode="stop")
    uri = server.get_uri()
    if "sslmode=" not in uri:
        uri = uri + ("&" if "?" in uri else "?") + "sslmode=disable"
    api_port = _free_port()
    port = int(os.environ.get("E2E_PORT") or _free_port())
    url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": uri,
            "HUB_ADDR": f"127.0.0.1:{api_port}",
            "HUB_PLUGINS": "off",
            "BLOB_DRIVER": "memory",
            "HUB_PUBLIC_URL": url,
            "HUB_REPO_ROOT": str(ROOT),
            "HUB_PROXY": f"http://127.0.0.1:{api_port}",
        }
    )
    log_path = Path("/tmp/jobos-e2e-hub.log")
    log_file = log_path.open("w", encoding="utf-8")
    api = subprocess.Popen(
        ["go", "run", "./cmd/hub"],
        cwd=str(ROOT / "server"),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    web = None
    try:
        _wait_http(f"http://127.0.0.1:{api_port}", timeout_s=60)
        subprocess.run(["npm", "run", "build"], cwd=str(ROOT / "web"), check=True, env=env)
        web = subprocess.Popen(
            ["npx", "vite", "preview", "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
            cwd=str(ROOT / "web"),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _wait_http(url, timeout_s=60)
    except Exception:
        log_file.flush()
        logs = log_path.read_text(encoding="utf-8")[-4000:]
        api.kill()
        if web:
            web.kill()
        server.cleanup()
        raise RuntimeError(f"local Hub failed to start: {logs}") from None

    def stop() -> None:
        for proc in (web, api):
            if proc is None:
                continue
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        log_file.close()
        server.cleanup()

    return HubHandle(url=url, backend="local", stop=stop)


@pytest.fixture(scope="session")
def hub() -> HubHandle:
    external = (os.environ.get("E2E_HUB_URL") or "").strip()
    if external and os.environ.get("E2E_BACKEND") != "compose":
        _wait_http(external, timeout_s=30)
        yield HubHandle(url=external.rstrip("/"), backend="external")
        return
    handle = _start_compose() if _docker_compose_available() else _start_local()
    try:
        yield handle
    finally:
        if handle.stop:
            handle.stop()


@pytest.fixture(scope="session")
def base_url(hub: HubHandle) -> str:
    return hub.url


@pytest.fixture(scope="session")
def browser_type_launch_args() -> dict:
    args = ["--disable-dev-shm-usage", "--no-sandbox"]
    launch: dict = {"args": args}
    channel = (os.environ.get("E2E_BROWSER_CHANNEL") or "").strip()
    if not channel:
        for candidate in ("/usr/local/bin/google-chrome", "/usr/bin/google-chrome"):
            if Path(candidate).is_file():
                channel = "chrome"
                break
    if channel:
        launch["channel"] = channel
    return launch


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict, base_url: str) -> dict:
    return {
        **browser_context_args,
        "base_url": base_url,
        "ignore_https_errors": True,
        "viewport": {"width": 1280, "height": 800},
    }
