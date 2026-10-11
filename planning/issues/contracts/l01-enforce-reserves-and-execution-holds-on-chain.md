# [CONTRACTS] Enforce reserves and execution holds on-chain

| Field | Value |
|---|---|
| **ID** | SC-L01 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | contracts |
| **Status** | Accepted |
| **Traces to** | BR-035, FR-223 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-028: On-chain reserve & execution-hold enforcement

Problem behind this work (from `docs/FEATURES.md`):

- **F-028** solves: Concurrent obligations competing for the same funds (database holds are not hard protection).

## Objective

Protect funds committed to other obligations at the contract level.

## Scope

- Reservation and hold storage per request
- R to L transition
- release on known outcome
- invariant tests

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Needs a design ADR first.

## Dependencies

- SC-014: Write the invariant and fuzz suite

## Acceptance criteria

- [ ] Invariant: reservations plus holds never exceed balance minus buffer

## Testing requirements

- Contract: invariants

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
