"""OpenTelemetry tracer provider shared by api, worker and signer.

Framework instrumentation (FastAPI, Celery, httpx, SQLAlchemy) lives in each service so py-core
stays free of those dependencies.
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_ENDPOINT_VARS = ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")


def configure_tracing(service: str) -> None:
    """Install the process tracer provider once (100 % sampling by default).

    Spans go to OTLP only when a standard ``OTEL_EXPORTER_OTLP_*ENDPOINT`` variable is set; without
    one they are still created, so trace context reaches logs and downstream services. The batch
    exporter runs off the request path, so a down collector never blocks the app.
    """

    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: f"treasurypilot-{service}"}))
    if any(os.environ.get(name) for name in _ENDPOINT_VARS):
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


__all__ = ["configure_tracing"]
