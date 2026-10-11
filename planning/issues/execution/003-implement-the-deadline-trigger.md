# [EXECUTION] Implement the deadline trigger

| Field | Value |
|---|---|
| **ID** | EXE-003 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-501–503, M10-D1 |
| **Blocks** | EXE-004, EXE-009 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-060: Deadline-driven autonomous trigger

Problem behind this work (from `docs/FEATURES.md`):

- **F-060** solves: Makes the agent a financial participant, not a button.

## Objective

The agent starts work by itself when approved requests enter their window.

## Scope

- Scheduling cycle every 15 min and on events
- execution cycle every 60 s as a safety net
- event hooks (approval, exception granted, resume, inflow, payee Active, fee accepted) enqueue an execution cycle immediately
- eligibility per docs/modules/execution §8.1 (today's schedule + window open)
- gates: backend pause flag, mandate active, coverage COMPLETE (or acknowledged), no Unknown operation, no Executing plan
- non-blocking per-treasury advisory lock

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

- [ ] An eligible request starts executing within 5 s of its approval with no user action
- [ ] Two events at once run one cycle (lock)
- [ ] A paused treasury or one with an Unknown operation is skipped with a logged reason

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
