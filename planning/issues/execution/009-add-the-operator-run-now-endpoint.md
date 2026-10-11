# [EXECUTION] Add the operator run-now endpoint

| Field | Value |
|---|---|
| **ID** | EXE-009 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-504 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-060: Deadline-driven autonomous trigger

Problem behind this work (from `docs/FEATURES.md`):

- **F-060** solves: Makes the agent a financial participant, not a button.

## Objective

Operators can trigger planning immediately, with the same safety gates.

## Scope

- POST /treasuries/{t}/run-now with Idempotency-Key
- same gates and errors as the scheduler

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- EXE-003: Implement the deadline trigger

## Acceptance criteria

- [ ] A paused treasury returns TREASURY_PAUSED
- [ ] The call enqueues exactly one job

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
