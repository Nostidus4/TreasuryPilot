"""One OpenTelemetry trace across the api -> worker -> signer path."""

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import httpx2
import pytest
import structlog
import uvicorn
from celery import signals
from celery.contrib.testing.worker import start_worker
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from treasurypilot_api.main import create_app as create_api_app
from treasurypilot_core.observability import clear_context
from treasurypilot_signer.main import create_app as create_signer_app
from treasurypilot_worker.celery_app import app
from treasurypilot_worker.runtime import SafeTask


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    # The worker's setup_logging receiver installs the global provider and Celery instrumentation.
    signals.setup_logging.send(
        sender=None, loglevel="INFO", logfile=None, format="", colorize=False
    )
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield exporter
    exporter.shutdown()
    clear_context()
    structlog.reset_defaults()


def test_one_api_request_is_one_trace_across_worker_and_signer(
    spans: InMemorySpanExporter,
) -> None:
    signer_app = create_signer_app()

    @signer_app.get("/_probe")
    async def signer_probe() -> None:
        return None

    @app.task(base=SafeTask, name="test.e2e-tracing", ignore_result=False)
    def worker_step(signer_url: str) -> None:
        # A real HTTP hop: the signer can only join the trace through the traceparent header.
        httpx2.get(f"{signer_url}/_probe")

    api_app: FastAPI = create_api_app()

    @api_app.post("/_enqueue")
    async def enqueue() -> None:
        worker_step.delay(signer_url)

    original = (app.conf.broker_url, app.conf.result_backend)
    app.conf.update(broker_url="memory://", result_backend="cache+memory://")
    try:
        with _serve(signer_app) as signer_url, start_worker(app, perform_ping_check=False):
            TestClient(api_app).post("/_enqueue")
            signer_span = _wait_for_span(spans, "GET /_probe")
    finally:
        app.tasks.pop("test.e2e-tracing", None)
        app.conf.update(broker_url=original[0], result_backend=original[1])

    finished = spans.get_finished_spans()
    by_name = {span.name: span for span in finished}
    by_span_id = {span.context.span_id: span for span in finished if span.context}
    api_span = by_name["POST /_enqueue"]
    worker_span = by_name["run/test.e2e-tracing"]
    assert signer_span.context is not None and api_span.context is not None
    assert worker_span.context is not None
    assert {
        api_span.context.trace_id,
        worker_span.context.trace_id,
        signer_span.context.trace_id,
    } == {api_span.context.trace_id}
    # The signer joins through the traceparent header of the worker's httpx call.
    assert signer_span.parent is not None
    assert by_span_id[signer_span.parent.span_id].kind is SpanKind.CLIENT


@contextmanager
def _serve(asgi_app: FastAPI) -> Iterator[str]:
    server = uvicorn.Server(
        uvicorn.Config(asgi_app, host="127.0.0.1", port=0, log_config=None, lifespan="off")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "signer server did not start within 10s"
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _wait_for_span(exporter: InMemorySpanExporter, name: str) -> ReadableSpan:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        for span in exporter.get_finished_spans():
            if span.name == name:
                return span
        time.sleep(0.05)
    names = [span.name for span in exporter.get_finished_spans()]
    raise AssertionError(f"no {name} span within 10s: {names}")
