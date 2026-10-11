# [EXECUTION] Run the liquidity cycle (supply / withdraw)

| Field | Value |
|---|---|
| **ID** | EXE-014 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-519, ADR-019 |
| **Blocks** | — |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-068: Idle-cash management on Aave V3 (SUPPLY / WITHDRAW)

Problem behind this work (from `docs/FEATURES.md`):

- **F-068** solves: idle cash earns nothing, while over-supplying risks missing a due payment.

## Objective

The agent keeps idle cash supplied and withdraws when obligations grow.

## Scope

- After request plans, at most one liquidity plan per cycle from decide_liquidity
- validate, attest, execute like a request plan
- leading WITHDRAW inside request plans when the reserve would break

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- EXE-008: Sequence steps with re-read and re-validation
- ENG-013: Implement reserve formulas and the liquidity decision
- SC-024: Implement Aave V3 supply and withdraw through Safe T

## Acceptance criteria

- [ ] D2: surplus is supplied with the reserve intact
- [ ] D3: a new approved invoice triggers a withdraw before payment

## Testing requirements

- Integration on the fork

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
