# [CONTRACTS] Implement mandate governance and versioning

| Field | Value |
|---|---|
| **ID** | SC-003 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
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

- configureMandate with validation (expiry > validFrom, executor ≠ 0, cooling ≥ 1, perRequest ≤ daily)
- setApprovers (keep ≥ 1)
- setBuffer (wallet known, buffer ≤ target)
- version increment
- validity-window modifier
- views

## Out of scope

Payees, limits enforcement.

## Technical notes

Governance check is `msg.sender == safeT`. Not upgradeable.

## Dependencies

- SC-021: Implement the module factory with EIP-1167 clones

## Acceptance criteria

- [ ] Calls from any address other than Safe T revert NotOwner
- [ ] Each invalid mandate field reverts InvalidMandate with the field
- [ ] Version increases by one per configureMandate and counters are untouched
- [ ] Executor calls revert MandateExpired after expiresAt

## Testing requirements

- Unit: governance access and validation matrix
- counters unchanged across versions

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
