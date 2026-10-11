# [CONTRACTS] Implement mandate governance and versioning

| Field | Value |
|---|---|
| **ID** | SC-003 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Review |
| **Traces to** | BR-015, BR-016, FR-204–207 |
| **Blocks** | SC-004, SC-010 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-021: Mandate activation, versioning & lifecycle

Problem behind this work (from `docs/FEATURES.md`):

- **F-021** solves: Policy must exist where it is enforced. A database copy is only a cache (GA p.11).

## Objective

Only Safe T can configure the mandate; every change bumps the version.

## Scope

- configureMandate, setApprovers, constructor/initializer binding the three Safes and the executor
- version increment
- expiry check modifier
- views for mandate and version

## Out of scope

Payees, limits enforcement.

## Technical notes

Governance check is `msg.sender == safeT`. Not upgradeable.

## Dependencies

- SC-002: Define module storage, structs, EIP-712 domain, errors and events

## Acceptance criteria

- [ ] A call from any address other than Safe T reverts
- [ ] Version increases by one per configureMandate
- [ ] Executor calls revert after expiresAt

## Testing requirements

- Unit: governance access tests
- expiry tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
