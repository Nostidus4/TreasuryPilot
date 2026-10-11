# [MANDATE] Implement pause and resume (backend and transactions)

| Field | Value |
|---|---|
| **ID** | MDT-007 |
| **Epic** | M03 · Mandate, Payees, Exceptions & Pause |
| **Module** | `mandate` ([spec](../../../docs/modules/mandate/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-062–BR-064, FR-218, FR-221 |
| **Blocks** | EXE-003, RCV-006, WEB-019 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Mandate, Payees, Exceptions & Pause**. It supports:

- F-026: Pause, resume & revoke

Problem behind this work (from `docs/FEATURES.md`):

- **F-026** solves: Emergency stop.

## Objective

Pausing takes effect in the backend immediately and on-chain after confirmation.

## Scope

- POST /pause sets the backend pause flag at once and returns the pause Safe transaction (or guardian call)
- resume-tx for the Owner
- status sync from Paused/Resumed events
- list of pending transactions at pause time

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

The trigger and executor check the flag before every action.

## Dependencies

- MDT-003: Implement mandate activation and read-back

## Acceptance criteria

- [ ] After POST /pause no new operation is created
- [ ] Guardian can pause but resume-tx is refused for them
- [ ] UI data distinguishes requested from effective

## Testing requirements

- Integration: AT-08

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
