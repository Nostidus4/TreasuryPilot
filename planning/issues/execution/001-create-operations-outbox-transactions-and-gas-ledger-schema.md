# [EXECUTION] Create operations (outbox), transactions and gas ledger schema

| Field | Value |
|---|---|
| **ID** | EXE-001 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | ADR-004, DATA_MODEL §2.6 |
| **Blocks** | CHR-003, EXE-007 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-061: Sequential executor & signer service

Problem behind this work (from `docs/FEATURES.md`):

- **F-061** solves: Key isolation from the LLM and the API process. Ordering safety.

## Objective

Durable records for every money-moving step.

## Scope

- Alembic migration and models
- unique step_id on operations
- indexes by treasury and status

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-001: Create invoice and request schema

## Acceptance criteria

- [ ] Inserting two operations with the same step_id fails

## Testing requirements

- Integration: migration test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
