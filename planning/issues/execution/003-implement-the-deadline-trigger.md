# [EXECUTION] Implement the deadline trigger

| Field | Value |
|---|---|
| **ID** | EXE-003 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-501–503 |
| **Blocks** | EXE-004, EXE-009 |

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-060: Deadline-driven autonomous trigger

Problem behind this work (from `docs/FEATURES.md`):

- **F-060** solves: Makes the agent a financial participant, not a button.

## Objective

The agent starts work by itself when approved requests enter their window.

## Scope

- Beat schedule per treasury
- eligibility query (Approved, within lead time or discount window)
- gates: backend pause flag, mandate active, coverage COMPLETE (or acknowledged), no Unknown operation
- enqueue planning

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Lead time is configurable (24h default, minutes in demo).

## Dependencies

- EXE-002: Set up Celery with core and ai queues
- INV-010: Implement approval typed data and signature verification
- MDT-007: Implement pause and resume (backend and transactions)
- TRS-007: Compute coverage and handle acknowledgment

## Acceptance criteria

- [ ] An eligible request triggers planning with no user action
- [ ] A paused treasury or one with an Unknown operation is skipped with a logged reason

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
