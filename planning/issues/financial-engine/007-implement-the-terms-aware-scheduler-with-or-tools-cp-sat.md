# [ENGINE] Implement the terms-aware scheduler with OR-Tools CP-SAT

| Field | Value |
|---|---|
| **ID** | ENG-007 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-052, FR-405, ADR-015, M07-D5, M07-D6, M07-D7 |
| **Blocks** | ENG-008, ENG-L01, ENG-L03, AGT-010 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-052: Terms-aware deterministic scheduler

Problem behind this work (from `docs/FEATURES.md`):

- **F-052** solves: P4: rules like "earliest due first" leave money on the table.

## Objective

Find the feasible schedule that maximizes value under the BR-052 priority order.

## Scope

- Solver interface (EDF, CPSAT, ORACLE implementations)
- CP-SAT model per docs/modules/financial-engine §8.4 (x[r,d], refill vars, constraints 1–8)
- lexicographic objective solved in stages (deadlines → value → tx count → approval order)
- determinism: 1 worker, fixed seed, sorted inputs
- 5 s time limit split across stages
- EDF fallback with status FALLBACK
- bounds guard (< 2^63) before model build
- add ortools to py-core (pinned)

## Out of scope

AI proposals (AGT-008). Oi→Oj refills (ENG-L01).

## Technical notes

ADR-015. Split into two PRs (model + staged objective) if it exceeds 2 days.

## Dependencies

- ENG-006: Implement the baseline scheduler B1 (earliest deadline first)
- ENG-012: Implement the exhaustive oracle scheduler for tests

## Acceptance criteria

- [ ] CP-SAT objective equals the oracle objective on all generated cases with N ≤ 8
- [ ] It never schedules an item that the validator would block
- [ ] It is never worse than EDF on the objective
- [ ] Same input twice gives byte-identical output
- [ ] A forced 1 ms limit returns the EDF schedule with status FALLBACK

## Testing requirements

- Unit: hand-computed optimum cases
- property: oracle equivalence, never worse than EDF, determinism
- timeout fallback

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
