# [ENGINE] Implement reserve formulas and the liquidity decision

| Field | Value |
|---|---|
| **ID** | ENG-013 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-037, BR-038, FR-519, ADR-019 |
| **Blocks** | ENG-014, EXE-014 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-068: Idle-cash management on Aave V3 (SUPPLY / WITHDRAW)

Problem behind this work (from `docs/FEATURES.md`):

- **F-068** solves: idle cash earns nothing, while over-supplying risks missing a due payment.

## Objective

One deterministic answer to 'supply, withdraw or do nothing' each cycle.

## Scope

- PaymentReserve, RequiredSafeReserve, AvailableForSupply, AccessibleLiquidity per docs/modules/financial-engine §15
- decide_liquidity with min_supply, 5 % withdraw margin and caps
- INSUFFICIENT_LIQUIDITY signal

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- ENG-002: Implement the liquidity calculator
- ENG-005: Model payment terms and their value function

## Acceptance criteria

- [ ] The D2 and D3 examples in §15 return SUPPLY 3,000 and WITHDRAW 2,625
- [ ] Nothing is supplied below min_supply
- [ ] A shortfall beyond Aave liquidity returns INSUFFICIENT_LIQUIDITY

## Testing requirements

- Unit + property

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
