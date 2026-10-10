# [AUDIT] Propagate coverage labels through the API

| Field | Value |
|---|---|
| **ID** | AUD-004 |
| **Epic** | M15 · Audit & Evidence |
| **Module** | `audit` ([spec](../../../docs/modules/audit/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-914 |
| **Blocks** | — |

## Context

This ticket belongs to the epic **Audit & Evidence**. It supports:

- F-122: Coverage & uncertainty labelling

Problem behind this work (from `docs/FEATURES.md`):

- **F-122** solves: Prevents false "safe" or "done" signals.

## Objective

Uncertainty is visible wherever a status is shown.

## Scope

- Coverage enum on snapshots, assessments and status DTOs
- missing-data list
- API responses include coverage

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- CHR-002: Implement block-consistent snapshots

## Acceptance criteria

- [ ] A stale snapshot is returned with coverage PARTIAL or UNKNOWN and the reason

## Testing requirements

- Unit

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
