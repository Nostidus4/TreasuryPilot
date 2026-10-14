"""Correlation ids across Celery headers and the api -> worker -> signer path."""

import json
import logging
import time
from collections.abc import Iterator

import pytest
import structlog
from celery import Task, signals
from celery.contrib.testing.worker import start_worker
from fastapi import FastAPI
from fastapi.testclient import TestClient

from treasurypilot_api.main import create_app as create_api_app
from treasurypilot_core.observability import (
    bind_context,
    clear_context,
    current_context,
)
from treasurypilot_signer.main import create_app as create_signer_app
from treasurypilot_worker.celery_app import app
from treasurypilot_worker.runtime import CORRELATION_ID_HEADER, LOG_CONTEXT_HEADER, SafeTask

CONTEXT = {
    "correlation_id": "corr-12345",
    "request_id": "req-12345",
    "org_id": "org-12345",
    "plan_id": "plan-12345",
    "operation_id": "op-12345",
}


@pytest.fixture(autouse=True)
def _clean_logging() -> Iterator[None]:
    clear_context()
    yield
    clear_context()
    structlog.reset_defaults()


class _CaptureContextTask(SafeTask):
    name = "test.capture-log-context"

    def run(self) -> dict[str, str]:
        return current_context()


def _published_headers(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    def capture_apply_async(
        _task: Task,
        args: tuple[object, ...] | None = None,
        kwargs: dict[str, object] | None = None,
        **options: object,
    ) -> None:
        del args, kwargs
        headers = options["headers"]
        assert isinstance(headers, dict)
        captured.update(headers)

    monkeypatch.setattr(Task, "apply_async", capture_apply_async)
    return captured


def test_publish_carries_the_current_log_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _published_headers(monkeypatch)
    _CaptureContextTask.bind(app)
    bind_context(**CONTEXT)

    _CaptureContextTask().apply_async()

    assert captured[CORRELATION_ID_HEADER] == "corr-12345"
    assert captured[LOG_CONTEXT_HEADER] == CONTEXT


def test_explicit_ids_override_the_publishers(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _published_headers(monkeypatch)
    _CaptureContextTask.bind(app)
    bind_context(**CONTEXT)

    _CaptureContextTask().apply_async(headers={LOG_CONTEXT_HEADER: {"operation_id": "op-other-1"}})

    assert captured[LOG_CONTEXT_HEADER] == {**CONTEXT, "operation_id": "op-other-1"}


def test_delivery_binds_all_ids_only_for_task_lifetime() -> None:
    _CaptureContextTask.bind(app)
    task = _CaptureContextTask()
    task.push_request(headers={LOG_CONTEXT_HEADER: CONTEXT, "unknown": "x"})
    try:
        assert task() == CONTEXT
        assert current_context() == {}
    finally:
        task.pop_request()


def test_delivery_without_log_context_falls_back_to_correlation_header() -> None:
    _CaptureContextTask.bind(app)
    task = _CaptureContextTask()
    task.push_request(headers={CORRELATION_ID_HEADER: "corr-12345"})
    try:
        assert task() == {"correlation_id": "corr-12345"}
    finally:
        task.pop_request()


def test_direct_call_without_headers_inherits_bound_correlation_id() -> None:
    _CaptureContextTask.bind(app)
    bind_context(correlation_id="corr-12345", request_id="req-12345")

    assert _CaptureContextTask()() == {"correlation_id": "corr-12345", "request_id": "req-12345"}


@pytest.mark.parametrize(
    "sent", ["not-a-dict", ["corr-12345"], {"correlation_id": "bad id", "org_id": "token:12345678"}]
)
def test_malformed_log_context_header_is_dropped(sent: object) -> None:
    _CaptureContextTask.bind(app)
    task = _CaptureContextTask()
    task.push_request(headers={LOG_CONTEXT_HEADER: sent, CORRELATION_ID_HEADER: "corr-12345"})
    try:
        assert task() == {"correlation_id": "corr-12345"}
    finally:
        task.pop_request()


def test_publish_drops_malformed_log_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _published_headers(monkeypatch)
    _CaptureContextTask.bind(app)
    bind_context(**CONTEXT)

    _CaptureContextTask().apply_async(
        headers={LOG_CONTEXT_HEADER: "oops", CORRELATION_ID_HEADER: "bad id"}
    )

    assert captured[LOG_CONTEXT_HEADER] == CONTEXT
    assert captured[CORRELATION_ID_HEADER] == "corr-12345"


def test_celery_logging_setup_configures_structlog(capsys: pytest.CaptureFixture[str]) -> None:
    # Celery sends setup_logging from both `celery worker` and `celery beat`.
    signals.setup_logging.send(
        sender=None, loglevel="INFO", logfile=None, format="", colorize=False
    )

    logging.getLogger("celery.beat").info("beat: Starting...")

    line = json.loads(capsys.readouterr().out)
    assert line["service"] == "worker"
    assert line["event"] == "beat: Starting..."


def test_one_request_id_finds_log_lines_in_api_worker_and_signer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    signer_app = create_signer_app()

    @signer_app.get("/_probe")
    async def signer_probe() -> None:
        structlog.get_logger().info("signer_probe")

    signer = TestClient(signer_app)

    @app.task(base=SafeTask, name="test.e2e-log-correlation", ignore_result=False)
    def worker_step() -> None:
        structlog.get_logger().info("worker_step")
        context = current_context()
        signer.get(
            "/_probe",
            headers={"X-Request-ID": context["request_id"], "X-Org-ID": context["org_id"]},
        )

    api_app: FastAPI = create_api_app()

    @api_app.post("/_enqueue")
    async def enqueue() -> None:
        structlog.get_logger().info("api_enqueue")
        worker_step.delay()

    log_lines: list[str] = []
    original = (app.conf.broker_url, app.conf.result_backend)
    app.conf.update(broker_url="memory://", result_backend="cache+memory://")
    try:
        with start_worker(app, perform_ping_check=False):
            response = TestClient(api_app).post(
                "/_enqueue", headers={"X-Request-ID": "req-12345", "X-Org-ID": "org-12345"}
            )
            assert response.headers["x-request-id"] == "req-12345"
            _wait_for(log_lines, capsys, "signer_probe")
    finally:
        app.tasks.pop("test.e2e-log-correlation", None)
        app.conf.update(broker_url=original[0], result_backend=original[1])

    lines = [json.loads(line) for line in log_lines]
    by_event = {line["event"]: line for line in lines}
    assert {"api_enqueue", "worker_step", "signer_probe"} <= set(by_event)
    for event in ("api_enqueue", "worker_step", "signer_probe"):
        assert by_event[event]["correlation_id"] == "req-12345", event
        assert by_event[event]["org_id"] == "org-12345", event


def _wait_for(sink: list[str], capsys: pytest.CaptureFixture[str], event: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        sink.extend(line for line in capsys.readouterr().out.splitlines() if line.startswith("{"))
        if any(f'"{event}"' in line for line in sink):
            return
        time.sleep(0.05)
    raise AssertionError(f"no {event} log line within 10s: {sink}")
