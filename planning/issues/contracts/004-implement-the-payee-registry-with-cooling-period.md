# [CONTRACTS] Implement the payee registry with cooling period

| Field | Value |
|---|---|
| **ID** | SC-004 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | contracts |
| **Status** | Ready for Review |
| **Traces to** | BR-013, BR-017, FR-208–210 |
| **Blocks** | SC-006 |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-022: Payee registry with screening & cooling period

Problem behind this work (from `docs/FEATURES.md`):

- **F-022** solves: Vendor/BEC fraud. An attacker who changes an address in an invoice cannot get paid quickly, and the Owner has time to notice (P3).

## Objective

Payees become payable only after their cooling period.

## Scope

- addPayee(payee, coolingSeconds) sets activeFrom
- deactivatePayee
- payeeStatus view
- internal `_requireActivePayee`

## Out of scope

Screening (off-chain).

## Technical notes

Re-adding a deactivated payee creates a fresh cooling period.

## Dependencies

- SC-003: Implement mandate governance and versioning

## Acceptance criteria

- [ ] A payee is not active before activeFrom and is active after
- [ ] Deactivated payees are rejected
- [ ] Only Safe T can add or deactivate

## Testing requirements

- Unit: time-warp tests around activeFrom

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
