# [OBSERVABILITY] Configure structured logging with correlation ids

| Field | Value |
|---|---|
| **ID** | OBS-001 |
| **Epic** | M17 · Observability & Analytics |
| **Module** | `observability` ([spec](../../../docs/modules/observability/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | infrastructure |
| **Status** | Ready for Review |
| **Traces to** | NFR-AUD-04, FR-923 |
| **Blocks** | OBS-002, OBS-003 |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Observability & Analytics**. It supports:

- F-142: System observability

Problem behind this work (from `docs/FEATURES.md`):

- **F-142** solves: Operating and debugging the system.

## Objective

Follow one request across services by id.

## Scope

- structlog JSON config shared by api, worker, signer
- bind org, request, plan and operation ids
- propagate through Celery headers

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- CMP-003: Implement data classification, encryption helpers and log redaction

## Acceptance criteria

- [ ] One request id finds its log lines in api, worker and signer

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
