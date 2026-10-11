# [CONTRACTS] Add on-chain request cancellation

| Field | Value |
|---|---|
| **ID** | SC-022 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | BR-077, FR-324, M05-D4 |
| **Blocks** | SC-014, INV-011 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-039: Payment request lifecycle & state machine

Problem behind this work (from `docs/FEATURES.md`):

- **F-039** solves: Unambiguous status. No single "Failed" state that erases history.

## Objective

A cancelled request can never be paid, even by a compromised backend.

## Scope

- requestCancelled mapping
- cancelRequest(requestId) callable by safeT or any current approver, idempotent, works while Paused
- reverts NotOwnerOrApprover and AlreadyPaid
- pay and refill revert RequestCancelled
- RequestCancelled(requestId, by) event
- invariant I11 in SC-014

## Out of scope

Undo of a cancellation (cancellation is permanent).

## Technical notes

An approver key compromise can only cancel (denial of service), never pay; documented in known-risks.

## Dependencies

- SC-006: Implement pay() core flow
- SC-009: Implement refill() bound to an approved request

## Acceptance criteria

- [ ] An approver and Safe T can cancel, a stranger cannot
- [ ] Pay and refill for a cancelled id revert RequestCancelled
- [ ] Cancelling a paid request reverts AlreadyPaid
- [ ] Cancel works while Paused

## Testing requirements

- Unit + invariant I11

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
