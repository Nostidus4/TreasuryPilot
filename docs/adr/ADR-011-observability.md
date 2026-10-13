# ADR-011: Observability stack
**Status:** Accepted (G2, 2026-10-11) · **Decision:** Q35

## Decision
- structlog JSON logs with `correlation_id`, `request_id`, `org_id`, `plan_id` and `operation_id`; redaction processors (F-113). `trace_id` is added by OBS-002 from the OpenTelemetry span.
- OpenTelemetry tracing for FastAPI, Celery, httpx and SQLAlchemy.
- Sentry for errors (web + Python).
- Prometheus `/metrics` covering queue depth, RPC errors, LLM latency/cost and transaction states.
- M1 dashboards are optional (Grafana); alerts go to Telegram.

## Consequences
Correlation ids must be propagated through Celery headers (`x_correlation_id`, `x_log_context`) and HTTP headers (`X-Request-ID`, `X-Org-ID`, `X-Plan-ID`, `X-Operation-ID`). Ids from HTTP headers are client-declared, not authenticated.

Stdlib logging (uvicorn, Celery, libraries) goes through the same root handler (`structlog.stdlib.ProcessorFormatter`), so it gets the same context, redaction and renderer.
