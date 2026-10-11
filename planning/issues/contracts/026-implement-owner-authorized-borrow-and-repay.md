# [CONTRACTS] Implement owner-authorized borrow and repay

| Field | Value |
|---|---|
| **ID** | SC-026 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P2 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | BR-044, FR-523, ADR-019 |
| **Blocks** | MDT-011 |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-079: Owner-authorized BORROW / REPAY execution

This is enabling work: other tickets cannot start, or evidence cannot be produced, without it.

## Objective

Borrowing only ever happens with an exact one-time owner authorization.

## Scope

- Governance authorizeBorrow/authorizeRepay stored per planId
- executor borrow(planId)/repay(planId)
- health factor check before and after
- one use
- events

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

P2 (D7).

## Dependencies

- SC-024: Implement Aave V3 supply and withdraw through Safe T

## Acceptance criteria

- [ ] Borrow without authorization reverts
- [ ] Health factor below the minimum reverts
- [ ] An authorization is usable once

## Testing requirements

- Unit + fork

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
