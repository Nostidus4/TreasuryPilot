# [MANDATE] Implement pause and resume (backend and transactions)

| Field | Value |
|---|---|
| **ID** | MDT-007 |
| **Epic** | M03 · Mandate, Payees, Exceptions & Pause |
| **Module** | `mandate` ([spec](../../../docs/modules/mandate/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
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

- POST /pause sets the backend pause flag at once and calls the sentinel (EXE-013) when configured, else returns a Guardian-Safe tx for the human guardian
- resume-tx and revoke-tx (typed name confirmation) via MDT-009
- status sync from Paused/Resumed/Revoked
- re-plan all queued requests after Resumed
- list of pending transactions at pause time

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

The trigger and executor check the flag before every action.

## Dependencies

- MDT-003: Implement mandate activation and read-back
- MDT-009: Build governance transactions and collect owner signatures in the app
- EXE-013: Add the pause-only sentinel to the signer

## Acceptance criteria

- [ ] After POST /pause no new operation is created
- [ ] With a sentinel configured the module is Paused within 2 blocks on Anvil
- [ ] Guardian can pause but resume-tx is refused for them
- [ ] UI data distinguishes requested from effective

## Testing requirements

- Integration: AT-08

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
