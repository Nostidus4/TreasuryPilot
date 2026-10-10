# ADR-011: Observability stack
**Status:** Accepted (G2, 2026-10-11) · **Decision:** Q35

## Decision
- structlog JSON logs with `trace_id`, `org_id`, `request_id`, `plan_id` and `operation_id`; redaction processors (F-113).
- OpenTelemetry tracing for FastAPI, Celery, httpx and SQLAlchemy.
- Sentry for errors (web + Python).
- Prometheus `/metrics` covering queue depth, RPC errors, LLM latency/cost and transaction states.
- M1 dashboards are optional (Grafana); alerts go to Telegram.

## Consequences
Correlation ids must be propagated through Celery headers.
