# [CONTRACTS] Implement the module factory with EIP-1167 clones

| Field | Value |
|---|---|
| **ID** | SC-021 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | ADR-002, M04-D2, M04-D9, ADR-019 |
| **Blocks** | SC-003, SC-016, TRS-006, SC-024 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-012: Module enablement & coverage verification
- F-021: Mandate activation, versioning & lifecycle

Problem behind this work (from `docs/FEATURES.md`):

- **F-012** solves: A second module with arbitrary execution would bypass the mandate (GA p.20).
- **F-021** solves: Policy must exist where it is enforced. A database copy is only a cache (GA p.11).

## Objective

Every treasury gets its own module clone, created and initialized safely by its own Safe T.

## Scope

- TreasuryPilotModuleFactory.create(asset, operational, mandate, approvers, buffers) callable by Safe T (msg.sender becomes safeT)
- EIP-1167 clone of a single implementation
- initialize() once, disabled on the implementation
- TreasuryModuleCreated event
- implementation() view for coverage checks
- create() takes aavePool; initialize() stores aavePool and verifies aToken via getReserveData(asset)

## Out of scope

Enabling the module on the Safes (done by the Owner, TRS-006).

## Technical notes

Use OpenZeppelin Clones. Clones share the implementation's runtime code, so coverage (TRS-007) checks the clone's target.

## Dependencies

- SC-002: Define module storage, structs, EIP-712 domain, errors and events

## Acceptance criteria

- [ ] A clone created by Safe T has safeT = that Safe and the given config
- [ ] Calling initialize again, or on the implementation, reverts
- [ ] Two treasuries get two clones with independent storage
- [ ] TreasuryModuleCreated is emitted

## Testing requirements

- Unit: factory, initialize protection, independence of clones

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
