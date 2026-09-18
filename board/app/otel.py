"""OpenTelemetry logs to stdout. No collector / OTLP endpoint.

Disable with ``OTEL_SDK_DISABLED=true`` or ``OTEL_LOGS_EXPORTER=none``.
"""

from __future__ import annotations

import logging
import os
import sys

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    ConsoleLogRecordExporter,
    LogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider

_LOG = logging.getLogger("jobos.hub")
_configured = False
_logger_provider: LoggerProvider | None = None
_instrumented_apps: set[int] = set()

_SERVICE_NAME = "jobos-hub"
_SERVICE_VERSION = "0.5.0"
_EXCLUDED_URLS = "/health,/health/"


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _logs_exporter_kind() -> str:
    return (os.environ.get("OTEL_LOGS_EXPORTER") or "console").strip().lower()


def _sdk_disabled() -> bool:
    return _env_flag("OTEL_SDK_DISABLED") or _logs_exporter_kind() == "none"


def _resource() -> Resource:
    return Resource.create(
        {
            SERVICE_NAME: os.environ.get("OTEL_SERVICE_NAME", _SERVICE_NAME) or _SERVICE_NAME,
            SERVICE_VERSION: _SERVICE_VERSION,
            "service.namespace": "jobos",
        }
    )


def _attach_stdlib(provider: LoggerProvider) -> None:
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=provider)
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
    for name in (
        "gunicorn",
        "gunicorn.error",
        "gunicorn.access",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "jobos.hub",
    ):
        logging.getLogger(name).propagate = True
    for name in (
        "opentelemetry",
        "opentelemetry.sdk",
        "opentelemetry.exporter",
    ):
        logging.getLogger(name).propagate = False
    LoggingInstrumentor().instrument(
        set_logging_format=False,
        enable_log_auto_instrumentation=False,
    )


def setup_otel(
    *,
    log_exporter: LogRecordExporter | None = None,
    force: bool = False,
) -> bool:
    """Configure OTEL logs to stdout. Returns True when the pipeline is active."""
    global _configured, _logger_provider
    if _configured and not force:
        return _logger_provider is not None
    if force and _logger_provider is not None:
        _logger_provider.shutdown()
        _logger_provider = None
        _configured = False

    if _sdk_disabled() and log_exporter is None:
        _configured = True
        return False

    exporter: LogRecordExporter = log_exporter or ConsoleLogRecordExporter(out=sys.stdout)
    provider = LoggerProvider(resource=_resource())
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    set_logger_provider(provider)
    _attach_stdlib(provider)
    trace.set_tracer_provider(TracerProvider(resource=_resource()))

    _logger_provider = provider
    _configured = True
    _LOG.info("OpenTelemetry logs enabled (stdout)")
    return True


def flush_otel_logs() -> None:
    if _logger_provider is not None:
        _logger_provider.force_flush()


def instrument_fastapi(app: FastAPI) -> None:
    if _logger_provider is None or _sdk_disabled():
        return
    app_id = id(app)
    if app_id in _instrumented_apps:
        return
    FastAPIInstrumentor.instrument_app(app, excluded_urls=_EXCLUDED_URLS)
    _instrumented_apps.add(app_id)


def reset_otel_for_tests() -> None:
    global _configured, _logger_provider
    if _logger_provider is not None:
        _logger_provider.shutdown()
    _logger_provider = None
    _configured = False
    _instrumented_apps.clear()
    try:
        inst = LoggingInstrumentor()
        if inst.is_instrumented_by_opentelemetry:
            inst.uninstrument()
    except Exception:
        pass
