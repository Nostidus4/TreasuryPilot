# [CHAIN] Detect reorgs and re-evaluate status

| Field | Value |
|---|---|
| **ID** | CHR-004 |
| **Epic** | M06 · Chain Reader & Tx Tracking |
| **Module** | `chain-reader` ([spec](../../../docs/modules/chain-reader/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-602 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Chain Reader & Tx Tracking**. It supports:

- F-070: Transaction tracking & confirmation

Problem behind this work (from `docs/FEATURES.md`):

- **F-070** solves: "Broadcast" is not "done". Paid only after confirmation (BR-053).

## Objective

A reorg cannot leave a payment falsely marked Paid.

## Scope

- Store block hash per confirmation
- re-check on later blocks
- demote to Pending when the block hash changes
- mark observed events removed

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- CHR-003: Implement the transaction tracker

## Acceptance criteria

- [ ] An Anvil reorg simulation moves the transaction back to Pending and the request out of Paid

## Testing requirements

- Integration: reorg simulation

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
