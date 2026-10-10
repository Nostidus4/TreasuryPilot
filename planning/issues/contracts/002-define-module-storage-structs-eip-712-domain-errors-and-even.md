# [CONTRACTS] Define module storage, structs, EIP-712 domain, errors and events

| Field | Value |
|---|---|
| **ID** | SC-002 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Review |
| **Traces to** | ADR-003, BR-003 |
| **Blocks** | SC-003, SC-005 |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-021: Mandate activation, versioning & lifecycle
- F-038: Invoice approval via EIP-712 signature

Problem behind this work (from `docs/FEATURES.md`):

- **F-021** solves: Policy must exist where it is enforced. A database copy is only a cache (GA p.11).
- **F-038** solves: Approval is cryptographic and bound to exact fields, not a backend flag.

## Objective

Fix the on-chain data model and interfaces before any logic is written.

## Scope

- ITreasuryPilotModule interface per docs/modules/contracts
- structs Mandate, PaymentApproval, OneTimeException
- EIP-712 domain and type hashes
- custom errors named like API error codes
- events for every state change

## Out of scope

Function bodies.

## Technical notes

Error names must match docs/API_SPEC.md §9 (e.g. PayeeCooling, OverDailyLimit).

## Dependencies

- SC-001: Set up the Foundry project with pinned dependencies

## Acceptance criteria

- [ ] Interface compiles and matches the module spec
- [ ] Type hashes are unit-tested against hand-computed values
- [ ] Each planned state change has an event

## Testing requirements

- Unit: type-hash tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
