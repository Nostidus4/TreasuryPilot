# [MANDATE] Implement mandate activation and read-back

| Field | Value |
|---|---|
| **ID** | MDT-003 |
| **Epic** | M03 · Mandate, Payees, Exceptions & Pause |
| **Module** | `mandate` ([spec](../../../docs/modules/mandate/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-015, FR-204–205 |
| **Blocks** | DEV-006, MDT-006, MDT-007, MDT-008, WEB-005 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Mandate, Payees, Exceptions & Pause**. It supports:

- F-021: Mandate activation, versioning & lifecycle

Problem behind this work (from `docs/FEATURES.md`):

- **F-021** solves: Policy must exist where it is enforced. A database copy is only a cache (GA p.11).

## Objective

A mandate becomes Active only when the chain says so.

## Scope

- activation-tx endpoint building the configureMandate Safe transaction
- activation endpoint recording the tx hash
- tracker task waits for confirmations, reads the on-chain mandate and compares with the draft hash
- status events

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- MDT-002: Validate mandate drafts and generate summary and diff
- TRS-006: Build the module deploy-and-enable Safe transaction
- CHR-003: Implement the transaction tracker

## Acceptance criteria

- [ ] Status moves Draft → PendingActivation → Active only after matching on-chain state
- [ ] A mismatch sets Discrepancy and does not activate
- [ ] Version history is immutable

## Testing requirements

- Integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
