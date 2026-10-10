# [ENGINE] Implement the terms-aware scheduler

| Field | Value |
|---|---|
| **ID** | ENG-007 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-052, FR-405 |
| **Blocks** | ENG-008, ENG-L01, ENG-L03, AGT-010 |

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-052: Terms-aware deterministic scheduler

Problem behind this work (from `docs/FEATURES.md`):

- **F-052** solves: P4: rules like "earliest due first" leave money on the table.

## Objective

Find the feasible schedule that maximizes value under the BR-052 priority order.

## Scope

- Exact search for N ≤ 12
- greedy plus pairwise-exchange improvement for larger N
- multi-day horizon honouring the daily cap per day
- output per-item planned date and expected value

## Out of scope

AI proposals (AGT-008).

## Technical notes

Lexicographic objective: violations (must be 0), missed feasible deadlines, value, tx count. Split into two PRs if it exceeds 2 days.

## Dependencies

- ENG-006: Implement the baseline scheduler B1 (earliest deadline first)

## Acceptance criteria

- [ ] On hand-computed cases the result equals the known optimum
- [ ] It never schedules an item that the validator would block
- [ ] It is never worse than B1 on the objective

## Testing requirements

- Unit: optimum cases
- property: never worse than EDF

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
