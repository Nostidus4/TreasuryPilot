# [CONTRACTS] Define module storage, structs, EIP-712 domain, errors and events

| Field | Value |
|---|---|
| **ID** | SC-002 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | ADR-003, BR-003, ADR-019 |
| **Blocks** | SC-005, SC-021 |
| **Submission cut** | A |

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

- ITreasuryPilotModule interface per docs/modules/contracts §6
- storage layout per §4 (mandate, buffers/targets, approvers, payees, counters, replay maps, exceptions, duplicate allowances)
- EIP-712 domain and the single PaymentApproval type hash
- custom errors exactly as listed in §6.2–6.4
- events per §6.6
- PaymentApproval with 13 fields (earlyAmount, earlyPayBy) per docs/modules/contracts §15
- Aave storage (aavePool, aToken) and supply Limits in the mandate
- new errors and events: Supplied, Withdrawn, SupplyFloorBreach, OverSupplyPerTx, OverSupplyDaily, InsufficientAToken, AllowanceNotCleared, WrongPaymentOption

## Out of scope

Function bodies.

## Technical notes

M04-D3: only PaymentApproval is an EIP-712 struct; exceptions and duplicate overrides are governance calls.

## Dependencies

- SC-001: Set up the Foundry project with pinned dependencies

## Acceptance criteria

- [ ] Interface compiles and matches docs/modules/contracts §6
- [ ] PaymentApproval type hash is unit-tested against a hand-computed value
- [ ] Every error name in §6.4 exists and matches a reason code in POL-001
- [ ] Each state change listed in §6.6 has an event

## Testing requirements

- Unit: type-hash tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
