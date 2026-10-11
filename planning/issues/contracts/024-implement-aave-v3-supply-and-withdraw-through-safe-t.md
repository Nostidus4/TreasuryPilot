# [CONTRACTS] Implement Aave V3 supply and withdraw through Safe T

| Field | Value |
|---|---|
| **ID** | SC-024 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | BR-037, BR-038, FR-520, ADR-019 |
| **Blocks** | SC-025, SC-026, EXE-014 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-068: Idle-cash management on Aave V3 (SUPPLY / WITHDRAW)

Problem behind this work (from `docs/FEATURES.md`):

- **F-068** solves: idle cash earns nothing, while over-supplying risks missing a due payment.

## Objective

Idle USDC earns in Aave without ever breaking the Safe floor.

## Scope

- supply(stepId, amount) and withdraw(stepId, amount) per docs/modules/contracts §15
- exact approve then pool.supply, allowance reset check
- floor = bufferOf[safeT]
- supply caps and counters
- balance-delta checks
- Supplied/Withdrawn events
- MockAavePool for unit tests

## Out of scope

Borrow/repay (SC-026).

## Technical notes

Fixed targets only: asset, aavePool, Safe T.

## Dependencies

- SC-021: Implement the module factory with EIP-1167 clones
- SC-007: Implement per-request limits and UTC daily counters
- SC-008: Enforce minimum buffers on pay and refill

## Acceptance criteria

- [ ] A supply leaving Safe T below its floor reverts SupplyFloorBreach
- [ ] Allowance is 0 after supply
- [ ] Withdraw returns exactly the amount to Safe T
- [ ] Non-executor calls revert

## Testing requirements

- Unit with MockAavePool

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
