# [CONTRACTS] Implement the payee registry with cooling period

| Field | Value |
|---|---|
| **ID** | SC-004 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | BR-013, BR-017, FR-208–210 |
| **Blocks** | SC-006 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-022: Payee registry with screening & cooling period

Problem behind this work (from `docs/FEATURES.md`):

- **F-022** solves: Vendor/BEC fraud. An attacker who changes an address in an invoice cannot get paid quickly, and the Owner has time to notice (P3).

## Objective

Payees become payable only after their cooling period.

## Scope

- addPayee(payee) with activeFrom = now + mandate.payeeCoolingSeconds
- deactivatePayee
- payeeStatus view
- reject treasury wallets as payees
- internal _requireActivePayee

## Out of scope

Screening (off-chain).

## Technical notes

M04-D5: cooling comes from the mandate, never from a per-call argument.

## Dependencies

- SC-003: Implement mandate governance and versioning

## Acceptance criteria

- [ ] A payee is not payable before activeFrom and is payable after
- [ ] Re-adding a deactivated payee restarts cooling
- [ ] Treasury wallets cannot be added as payees
- [ ] Only Safe T can add or deactivate

## Testing requirements

- Unit: time-warp tests around activeFrom

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
