"""Unhandled errors reach Sentry tagged with the correlation id, redacted, and alert Telegram."""

import io
import time
import urllib.request
from typing import Any

import pytest
import sentry_sdk
import structlog
from celery import signals
from celery.app import trace as celery_trace
from celery.contrib.testing.worker import start_worker
from celery.worker.consumer import consumer
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from treasurypilot_api.main import create_app as create_api_app
from treasurypilot_core import error_tracking
from treasurypilot_core.observability import bind_context, clear_context
from treasurypilot_worker.celery_app import app
from treasurypilot_worker.runtime import SafeTask


class _CapturingTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        self.events.extend(
            item.payload.json
            for item in envelope.items
            if item.type == "event" and item.payload.json
        )


@pytest.fixture
def telegram(monkeypatch: pytest.MonkeyPatch) -> list[urllib.request.Request]:
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.invalid/1")
    monkeypatch.setenv("TP_TELEGRAM_BOT_TOKEN", "123456789:test-bot-token")
    monkeypatch.setenv("TP_TELEGRAM_ALERT_CHAT_ID", "-100123")
    sent: list[urllib.request.Request] = []
    monkeypatch.setattr(
        error_tracking.urllib.request,
        "urlopen",
        lambda request, **_: sent.append(request) or io.BytesIO(),
    )
    return sent


def _install_transport() -> _CapturingTransport:
    transport = _CapturingTransport()
    sentry_sdk.get_client().transport = transport
    return transport


def test_api_500_reaches_sentry_with_the_request_id(
    telegram: list[urllib.request.Request],
) -> None:
    api_app: FastAPI = create_api_app()
    transport = _install_transport()

    @api_app.get("/_boom")
    async def boom() -> None:
        raise RuntimeError("db_password=hunter2 rejected")

    try:
        response = TestClient(api_app, raise_server_exceptions=False).get(
            "/_boom", headers={"X-Request-ID": "req-12345"}
        )
        sentry_sdk.flush()
    finally:
        sentry_sdk.init(dsn="")
        clear_context()
        structlog.reset_defaults()

    assert response.status_code == 500
    [event] = transport.events
    assert event["tags"]["correlation_id"] == "req-12345"
    assert event["tags"]["service"] == "api"
    assert event["exception"]["values"][-1]["value"] == "db_password=[REDACTED] rejected"
    [alert] = _wait_for(telegram)
    assert alert.data is not None
    assert b"req-12345" in alert.data
    assert b"hunter2" not in alert.data


def test_failed_task_reaches_sentry_with_the_publishers_correlation_id(
    telegram: list[urllib.request.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Celery sends setup_logging on worker start; the receiver initialises Sentry.
    signals.setup_logging.send(
        sender=None, loglevel="INFO", logfile=None, format="", colorize=False
    )
    # Prefork children import build_tracer lazily, so they get Sentry's patched one; the
    # in-thread test worker's consumer bound the original at import time.
    monkeypatch.setattr(consumer, "build_tracer", celery_trace.build_tracer)

    @app.task(base=SafeTask, name="test.sentry-failure")
    def failing_step() -> None:
        raise ValueError("boom")

    original = (app.conf.broker_url, app.conf.result_backend)
    app.conf.update(broker_url="memory://", result_backend="cache+memory://")
    try:
        with start_worker(app, perform_ping_check=False):
            transport = _install_transport()  # after start: the worker re-sends setup_logging
            bind_context(correlation_id="corr-12345")
            failing_step.delay()
            clear_context()
            _wait_for(transport.events)
    finally:
        app.tasks.pop("test.sentry-failure", None)
        app.conf.update(broker_url=original[0], result_backend=original[1])
        sentry_sdk.init(dsn="")
        clear_context()
        structlog.reset_defaults()

    [event] = transport.events
    assert event["tags"]["correlation_id"] == "corr-12345"
    assert event["tags"]["service"] == "worker"
    [alert] = _wait_for(telegram)
    assert alert.data is not None
    assert b"corr-12345" in alert.data


def test_handled_errors_do_not_alert(telegram: list[urllib.request.Request]) -> None:
    error_tracking.configure_error_tracking("api")
    transport = _install_transport()
    try:
        sentry_sdk.capture_exception(ValueError("expected"))
        sentry_sdk.flush()
    finally:
        sentry_sdk.init(dsn="")

    assert len(transport.events) == 1
    time.sleep(0.1)
    assert telegram == []


def _wait_for[T](items: list[T]) -> list[T]:
    deadline = time.monotonic() + 10
    while not items:
        assert time.monotonic() < deadline, "nothing arrived within 10s"
        time.sleep(0.05)
    return items
