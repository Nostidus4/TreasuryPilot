# [OBSERVABILITY] Add Sentry and Prometheus metrics

| Field | Value |
|---|---|
| **ID** | OBS-003 |
| **Epic** | M17 · Observability & Analytics |
| **Module** | `observability` ([spec](../../../docs/modules/observability/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
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

Know when something breaks.

## Scope

- Sentry in Python services and web
- /metrics with queue depth, RPC errors, LLM latency and cost, tx states
- Telegram alert hook

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- OBS-001: Configure structured logging with correlation ids

## Acceptance criteria

- [ ] A raised exception appears in Sentry with the correlation id
- [ ] Metrics endpoint exposes the listed series

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
