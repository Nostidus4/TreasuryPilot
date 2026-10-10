# [OBSERVABILITY] Add OpenTelemetry tracing

| Field | Value |
|---|---|
| **ID** | OBS-002 |
| **Epic** | M17 · Observability & Analytics |
| **Module** | `observability` ([spec](../../../docs/modules/observability/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | infrastructure |
| **Status** | Ready for Review |
| **Traces to** | ADR-011 |
| **Blocks** | — |

## Context

This ticket belongs to the epic **Observability & Analytics**. It supports:

- F-142: System observability

Problem behind this work (from `docs/FEATURES.md`):

- **F-142** solves: Operating and debugging the system.

## Objective

See where time goes.

## Scope

- Instrument FastAPI, Celery, httpx, SQLAlchemy
- trace context through tasks and the signer call
- OTLP exporter config

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- OBS-001: Configure structured logging with correlation ids

## Acceptance criteria

- [ ] A planning run shows one trace spanning api/worker/signer

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
