# [OBSERVABILITY] Compute operational metrics

| Field | Value |
|---|---|
| **ID** | OBS-004 |
| **Epic** | M17 · Observability & Analytics |
| **Module** | `observability` ([spec](../../../docs/modules/observability/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | infrastructure |
| **Status** | Ready for Review |
| **Traces to** | FR-921 |
| **Blocks** | OBS-005, ADM-L02 |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Observability & Analytics**. It supports:

- F-140: Operational metrics

Problem behind this work (from `docs/FEATURES.md`):

- **F-140** solves: Measurable value. Honest reporting.

## Objective

Numbers for completion, interventions, fees and latency.

## Scope

- Metric definitions document
- queries over events for completion rate, on-time %, interventions per request, fees, tx count, latency split by phase, rejections by reason
- GET /metrics/operations

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- AUD-001: Implement the hash-chained audit log
- EXE-008: Sequence steps with re-read and re-validation

## Acceptance criteria

- [ ] Each metric has a written definition and a test on a seeded dataset
- [ ] Rejected requests are included

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
