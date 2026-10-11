# [TREASURY] Build a Safe deployment transaction from the UI

| Field | Value |
|---|---|
| **ID** | TRS-008 |
| **Epic** | M02 · Treasury & Chain Configuration |
| **Module** | `treasury` ([spec](../../../docs/modules/treasury/README.md)) |
| **Phase / Priority** | M1 / P2 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-104 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Treasury & Chain Configuration**. It supports:

- F-011: Safe smart-account connection

Problem behind this work (from `docs/FEATURES.md`):

- **F-011** solves: Enforcement is only real if every wallet in scope supports the control path. A backend check in front of an EOA is not enforcement (Domain §6.2).

## Objective

Create a new Safe without leaving the app.

## Scope

- Endpoint returning the Safe factory transaction for the Owner to sign
- record the new address

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- TRS-004: Implement treasury creation with Safe verification

## Acceptance criteria

- [ ] A Safe deployed through the flow is usable in treasury creation

## Testing requirements

- Integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
