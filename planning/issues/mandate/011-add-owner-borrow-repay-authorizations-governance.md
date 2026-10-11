# [MANDATE] Add owner borrow/repay authorizations (governance)

| Field | Value |
|---|---|
| **ID** | MDT-011 |
| **Epic** | M03 · Mandate, Payees, Exceptions & Pause |
| **Module** | `mandate` ([spec](../../../docs/modules/mandate/README.md)) |
| **Phase / Priority** | M1 / P2 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-044, ADR-019 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Mandate, Payees, Exceptions & Pause**. It supports:

- F-079: Owner-authorized BORROW / REPAY execution

This is enabling work: other tickets cannot start, or evidence cannot be produced, without it.

## Objective

The Owner authorizes one exact borrow or repay through Safe T.

## Scope

- Governance txs authorizeBorrow/authorizeRepay built from a borrow proposal
- tracking
- UI hook in WEB-027

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

P2.

## Dependencies

- MDT-009: Build governance transactions and collect owner signatures in the app
- SC-026: Implement owner-authorized borrow and repay

## Acceptance criteria

- [ ] An authorization built from a proposal carries exactly its amount, expiry and minimum health factor

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
