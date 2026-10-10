# [WEB] Build the payee registry UI

| Field | Value |
|---|---|
| **ID** | WEB-006 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | frontend |
| **Status** | Ready for Review |
| **Traces to** | FR-208–211 |
| **Blocks** | — |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-134: Mandate & payee management UI
- F-022: Payee registry with screening & cooling period

Problem behind this work (from `docs/FEATURES.md`):

- **F-134** solves: Safe configuration by non-developers.
- **F-022** solves: Vendor/BEC fraud. An attacker who changes an address in an invoice cannot get paid quickly, and the Owner has time to notice (P3).

## Objective

Manage payees with screening and cooling visible.

## Scope

- List with status, screening result and cooling countdown
- propose form (Operator)
- Owner sign for registration and deactivation
- address-change flow that explains the new cooling period

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-004: Build the treasury setup wizard
- MDT-005: Build payee registration and deactivation transactions and sync status

## Acceptance criteria

- [ ] A new payee shows Screening, then Cooling with a countdown, then Active
- [ ] Only the Owner sees the sign action

## Testing requirements

- E2E on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
