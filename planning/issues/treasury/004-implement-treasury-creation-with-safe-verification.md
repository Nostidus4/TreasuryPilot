# [TREASURY] Implement treasury creation with Safe verification

| Field | Value |
|---|---|
| **ID** | TRS-004 |
| **Epic** | M02 · Treasury & Chain Configuration |
| **Module** | `treasury` ([spec](../../../docs/modules/treasury/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-101–103 |
| **Blocks** | DEV-006, TRS-005, TRS-006, TRS-008, TRS-L01, CHR-002 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Treasury & Chain Configuration**. It supports:

- F-010: Treasury creation
- F-011: Safe smart-account connection

Problem behind this work (from `docs/FEATURES.md`):

- **F-010** solves: Defines the scope of the money the agent manages.
- **F-011** solves: Enforcement is only real if every wallet in scope supports the control path. A backend check in front of an EOA is not enforcement (Domain §6.2).

## Objective

An Owner can register a treasury made of real Safes.

## Scope

- POST /orgs/{o}/treasuries
- verify each address is a Safe proxy on that chain (code hash / singleton)
- reject duplicates, wrong chain and EOAs
- GET treasury with wallets

## Out of scope

Coverage (TRS-007).

## Technical notes

Use safe-eth-py for Safe detection.

## Dependencies

- TRS-003: Implement the asset registry with on-chain decimals check
- IDN-006: Implement RBAC dependencies and tenant isolation

## Acceptance criteria

- [ ] An EOA is rejected with NOT_A_SAFE
- [ ] Duplicate wallet addresses are rejected
- [ ] A valid set of three Safes creates the treasury

## Testing requirements

- Integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
