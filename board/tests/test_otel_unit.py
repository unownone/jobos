"""OpenTelemetry log pipeline (no FastAPI boot)."""

from __future__ import annotations

import logging

import pytest
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter

from app.otel import flush_otel_logs, reset_otel_for_tests, setup_otel

pytestmark = pytest.mark.unit


def _bodies(exporter: InMemoryLogRecordExporter) -> list[str]:
    return [str(item.log_record.body) for item in exporter.get_finished_logs()]


def test_setup_defaults_to_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.delenv("OTEL_LOGS_EXPORTER", raising=False)
    reset_otel_for_tests()
    assert setup_otel(force=True) is True
    reset_otel_for_tests()


def test_sdk_disabled_skips_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    reset_otel_for_tests()
    assert setup_otel(force=True) is False


def test_stdlib_logs_reach_otel_exporter() -> None:
    reset_otel_for_tests()
    exporter = InMemoryLogRecordExporter()
    assert setup_otel(log_exporter=exporter, force=True) is True
    logging.getLogger("jobos.hub").info("hub-otel-probe")
    flush_otel_logs()
    bodies = _bodies(exporter)
    assert any("hub-otel-probe" in body for body in bodies)
    reset_otel_for_tests()
