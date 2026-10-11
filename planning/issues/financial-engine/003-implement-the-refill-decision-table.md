# [ENGINE] Implement the refill decision table

| Field | Value |
|---|---|
| **ID** | ENG-003 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-031, BR-033, BR-036, FR-404 |
| **Blocks** | ENG-004, ENG-006, ENG-011 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-051: Liquidity calculator

Problem behind this work (from `docs/FEATURES.md`):

- **F-051** solves: Amounts are never computed by the LLM (BR-034).

## Objective

Turn calculator outputs into one of: no refill, refill preferred, refill shortage, stop.

## Scope

- decide_refill per docs/modules/financial-engine §8.1 returning none / preferred / shortage / stop with a reason code
- refill amount = min(PreferredRefill, Bound) (M07-D4)
- stop REFILL_BOUND when Shortage > Bound
- stop SOURCE_INSUFFICIENT or OVER_REFILL_DAILY when Cap < Shortage

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

M07-D4: the other held requests in the same wallet refill for themselves when they are processed. Reason codes come from POL-001.

## Dependencies

- ENG-002: Implement the liquidity calculator

## Acceptance criteria

- [ ] The five rows of the §8.1 table return exactly the documented decision and amount
- [ ] No refill is proposed only to reach target
- [ ] The refill amount never exceeds the contract bound (BR-036)

## Testing requirements

- Unit: decision table tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
