# [WEB] Build the treasury setup wizard

| Field | Value |
|---|---|
| **ID** | WEB-004 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | frontend |
| **Status** | Ready for Review |
| **Traces to** | FR-101, FR-106 |
| **Blocks** | WEB-005, WEB-006, WEB-010 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-010: Treasury creation
- F-011: Safe smart-account connection
- F-012: Module enablement & coverage verification

Problem behind this work (from `docs/FEATURES.md`):

- **F-010** solves: Defines the scope of the money the agent manages.
- **F-011** solves: Enforcement is only real if every wallet in scope supports the control path. A backend check in front of an EOA is not enforcement (Domain §6.2).
- **F-012** solves: A second module with arbitrary execution would bypass the mandate (GA p.20).

## Objective

Owners register Safes, enable the module and see coverage.

## Scope

- Wizard: chain and asset, wallet addresses with validation feedback, module deploy and enable transactions signed in the wallet, coverage result
- TEST labels for test assets

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-003: Add wallet connection and SIWE linking
- TRS-007: Compute coverage and handle acknowledgment

## Acceptance criteria

- [ ] An Owner completes setup and sees coverage COMPLETE
- [ ] A non-Safe address shows the API error next to the field

## Testing requirements

- E2E on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
