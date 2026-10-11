# [CONTRACTS] Add Aave integration tests on a pinned Sepolia fork

| Field | Value |
|---|---|
| **ID** | SC-025 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | ADR-019, V3-11 |
| **Blocks** | — |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-068: Idle-cash management on Aave V3 (SUPPLY / WITHDRAW)
- F-163: Security test suites

Problem behind this work (from `docs/FEATURES.md`):

- **F-068** solves: idle cash earns nothing, while over-supplying risks missing a due payment.
- **F-163** solves: Evidence for the Security criterion.

## Objective

Prove supply and withdraw against the real Aave V3 contracts deterministically.

## Scope

- Anvil fork of Sepolia at a pinned block in CI
- deploy module + Safes on the fork
- supply, withdraw, account data and aToken accrual
- D2 and D3 as fork tests

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- SC-024: Implement Aave V3 supply and withdraw through Safe T
- SC-016: Write deployment scripts and the deployments manifest

## Acceptance criteria

- [ ] D2 and D3 pass on the fork
- [ ] Results are identical across runs (pinned block)

## Testing requirements

- Integration (fork)

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
