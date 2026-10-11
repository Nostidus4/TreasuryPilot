# [MANDATE] Build payee registration and deactivation transactions and sync status

| Field | Value |
|---|---|
| **ID** | MDT-005 |
| **Epic** | M03 · Mandate, Payees, Exceptions & Pause |
| **Module** | `mandate` ([spec](../../../docs/modules/mandate/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-013, BR-017, FR-208–210 |
| **Blocks** | WEB-006 |
| **Submission cut** | B |

## Context

This ticket belongs to the epic **Mandate, Payees, Exceptions & Pause**. It supports:

- F-022: Payee registry with screening & cooling period

Problem behind this work (from `docs/FEATURES.md`):

- **F-022** solves: Vendor/BEC fraud. An attacker who changes an address in an invoice cannot get paid quickly, and the Owner has time to notice (P3).

## Objective

Payee status in the app always reflects the on-chain allowlist and cooling period.

## Scope

- registration-tx and deactivation-tx endpoints
- status sync from PayeeAdded/PayeeDeactivated events
- activeFrom stored
- address change creates a new payee and deactivates the old one

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Cooling seconds come from org settings (24h default, 5 min demo).

## Dependencies

- MDT-004: Implement vendor and payee proposals with screening
- CHR-005: Index module and Safe events

## Acceptance criteria

- [ ] After the Owner's transaction the payee shows Cooling with the correct activeFrom, then Active
- [ ] Changing an address restarts cooling

## Testing requirements

- Integration on Anvil with time travel

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
