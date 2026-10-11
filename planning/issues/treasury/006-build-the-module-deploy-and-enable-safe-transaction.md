# [TREASURY] Build the module deploy-and-enable Safe transaction

| Field | Value |
|---|---|
| **ID** | TRS-006 |
| **Epic** | M02 · Treasury & Chain Configuration |
| **Module** | `treasury` ([spec](../../../docs/modules/treasury/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-204 |
| **Blocks** | TRS-007, MDT-003, MDT-010 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Treasury & Chain Configuration**. It supports:

- F-012: Module enablement & coverage verification

Problem behind this work (from `docs/FEATURES.md`):

- **F-012** solves: A second module with arbitrary execution would bypass the mandate (GA p.20).

## Objective

The Owner can deploy the treasury's module and enable it on all three Safes from the UI.

## Scope

- Endpoint returning a Safe T transaction that calls factory.create with the treasury config
- then enableModule on T, O1, O2 (MultiSend batch)
- record the module address from TreasuryModuleCreated after confirmation

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

For a 1-of-1 Safe the UI signs and executes directly.

## Dependencies

- TRS-004: Implement treasury creation with Safe verification
- SC-016: Write deployment scripts and the deployments manifest
- SC-021: Implement the module factory with EIP-1167 clones
- MDT-009: Build governance transactions and collect owner signatures in the app

## Acceptance criteria

- [ ] After the Owner executes the transactions the module is enabled on all three Safes
- [ ] The treasury record stores the module address

## Testing requirements

- Integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
