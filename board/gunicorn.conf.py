"""Production Gunicorn settings for the Hub (Uvicorn ASGI workers)."""

from __future__ import annotations

import os

bind = "{host}:{port}".format(
    host=os.environ.get("BOARD_HOST", "0.0.0.0"),
    port=os.environ.get("PORT") or os.environ.get("BOARD_PORT", "8787"),
)
wsgi_app = "app.main:create_app"
factory = True
worker_class = "uvicorn_worker.UvicornWorker"


def _workers() -> int:
    raw = os.environ.get("WEB_CONCURRENCY") or os.environ.get("GUNICORN_WORKERS")
    if raw:
        return max(1, int(raw))
    cpus = os.cpu_count() or 2
    return max(2, min(2 * cpus + 1, 8))


workers = _workers()
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")
proc_name = "jobos-hub"
# Docker/K8s own the process; Gunicorn's extra control socket is unused.
control_socket_disable = True
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "*")
# Each worker must call create_app() itself — do not inherit DB connections.
preload_app = False
